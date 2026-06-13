import glob
import http.client
import json
import os
import random
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

import yaml
from prometheus_client import Counter, Gauge, start_http_server

# Directory watched for SLO YAML definitions
SLO_DIR         = os.getenv("SLO_DIR",         "/definitions")
# Seconds between simulation cycles
CHECK_INTERVAL  = int(os.getenv("CHECK_INTERVAL",  "15"))
# Seconds between directory scans for new definitions
WATCH_INTERVAL  = int(os.getenv("WATCH_INTERVAL",  "30"))
# Name of the Pyrra container to restart when a new definition is found
PYRRA_CONTAINER = os.getenv("PYRRA_CONTAINER", "pyrra_filesystem")
DOCKER_SOCK     = "/var/run/docker.sock"

# Monotonically increasing counters scraped by Prometheus every 10s
SLI_CHECKS = Counter('sli_checks_total', 'Total SLI checks', ['service', 'check'])
SLI_ERRORS = Counter('sli_errors_total', 'SLI violations',   ['service', 'check'])
# Gauge exposing the last simulated or real metric value (informational only)
SLI_VALUE  = Gauge(  'sli_current_value','Simulated value',  ['service', 'check'])

# Per-check Gaussian simulators: each lambda returns (value, ok_condition)
SIMULATORS = {
    ("cv-analyzer", "latency"):    lambda: (random.gauss(0.08, 0.03), lambda v: v <= 0.1),
    ("cv-analyzer", "quality"):    lambda: (random.gauss(300, 20),    lambda v: v >= 288),
    ("qr-detector", "latency"):    lambda: (random.gauss(0.03, 0.01), lambda v: v <= 0.05),
    ("qr-detector", "quality"):    lambda: (random.gauss(820, 50),    lambda v: v >= 800),
    ("qr-detector", "throughput"): lambda: (random.gauss(7, 2),       lambda v: v >= 5),
}

# Default error rate for checks without a specific simulator entry
DEFAULT_ERROR_RATE = 0.02

# Maps condition strings from YAML annotations to comparison functions
_COND_OPS = {
    "<=": lambda v, t: v <= t,
    ">=": lambda v, t: v >= t,
    "<":  lambda v, t: v < t,
    ">":  lambda v, t: v > t,
    "==": lambda v, t: v == t,
    "!=": lambda v, t: v != t,
}


def default_sim():
    # Generic simulator: passes 98% of the time, fails 2%
    ok = random.random() > DEFAULT_ERROR_RATE
    return (1.0 if ok else 0.0, lambda v: v > 0.5)


def query_prometheus(prom_url: str, query: str) -> float | None:
    # Executes an instant PromQL query and returns the first scalar result
    url = f"{prom_url}/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        result = data.get("data", {}).get("result", [])
        if result:
            return float(result[0]["value"][1])
    except Exception as e:
        print(f"[warn] query prometheus falló ({query}): {e}")
    return None


def make_real_sim(cfg: dict):
    # Returns a sim() closure that queries a real Prometheus on each call
    def sim():
        value = query_prometheus(cfg["prometheus_url"], cfg["query"])
        if value is None:
            # Treat connectivity failures as passing to avoid penalising availability
            return (0.0, lambda v: True)
        threshold = cfg["threshold"]
        op = _COND_OPS.get(cfg["condition"], lambda v, t: True)
        return (value, lambda v: op(v, threshold))
    return sim


def discover_checks(slo_dir: str) -> tuple[set[tuple[str, str]], dict]:
    # Scans YAML files and returns the set of (service, check) pairs and real-metric configs
    found = set()
    real  = {}
    for path in glob.glob(os.path.join(slo_dir, "*.yaml")):
        try:
            with open(path) as f:
                obj = yaml.safe_load(f)
            errors_metric = (
                obj.get("spec", {})
                   .get("indicator", {})
                   .get("ratio", {})
                   .get("errors", {})
                   .get("metric", "")
            )
            # Only process definitions that use the SLI Bridge counter pattern
            if not errors_metric.startswith("sli_errors_total"):
                continue
            service = re.search(r'service="([^"]+)"', errors_metric)
            check   = re.search(r'check="([^"]+)"',   errors_metric)
            if service and check:
                key = (service.group(1), check.group(1))
                found.add(key)
                annotations = obj.get("metadata", {}).get("annotations", {}) or {}
                if annotations.get("bridge.real") == "true":
                    real[key] = {
                        "query":          annotations.get("bridge.query", ""),
                        "threshold":      float(annotations.get("bridge.threshold", "0")),
                        "condition":      annotations.get("bridge.condition", "<="),
                        "prometheus_url": annotations.get("bridge.prometheus_url", "http://localhost:9090"),
                    }
        except Exception as e:
            print(f"[warn] no se pudo leer {path}: {e}")
    return found, real


class _UnixHTTP(http.client.HTTPConnection):
    # HTTPConnection subclass that connects via a Unix domain socket instead of TCP
    def __init__(self, sock_path: str):
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._sock_path)


def restart_container(name: str) -> bool:
    # Sends POST /containers/{name}/restart to the Docker daemon via the Unix socket
    if not os.path.exists(DOCKER_SOCK):
        print(f"[warn] Docker socket no disponible — no se puede reiniciar {name}")
        return False
    try:
        conn = _UnixHTTP(DOCKER_SOCK)
        conn.request("POST", f"/containers/{name}/restart")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        print(f"[info] contenedor {name} reiniciado (HTTP {resp.status})")
        return resp.status in (204, 200)
    except Exception as e:
        print(f"[warn] no se pudo reiniciar {name}: {e}")
        return False


# Shared state between sim_loop and watch_loop — protected by _lock
_lock          = threading.Lock()
_active_checks: set[tuple[str, str]] = set()
_real_configs:  dict[tuple[str, str], dict] = {}


def _init_counters(checks: set[tuple[str, str]]):
    # Pre-registers label combinations so they appear in /metrics from the first scrape
    for service, check in checks:
        SLI_CHECKS.labels(service=service, check=check)
        SLI_ERRORS.labels(service=service, check=check)
        SLI_VALUE.labels(service=service, check=check)


def _get_sim(service: str, check: str):
    # Returns the appropriate simulator: real > specific > default
    with _lock:
        cfg = _real_configs.get((service, check))
    if cfg:
        return make_real_sim(cfg)
    return SIMULATORS.get((service, check), default_sim)


def watch_loop():
    # Background thread: scans /definitions/ every 30s and restarts Pyrra when new checks appear
    while True:
        time.sleep(WATCH_INTERVAL)
        current, real = discover_checks(SLO_DIR)
        with _lock:
            new = current - _active_checks
        if new:
            print(f"[info] nuevos checks detectados: {sorted(new)}")
            _init_counters(new)
            with _lock:
                _active_checks.update(new)
                _real_configs.update(real)
            restart_container(PYRRA_CONTAINER)


def sim_loop():
    # Main loop: generates one check per active SLO every 15s and updates the counters
    while True:
        with _lock:
            # Copy to minimise lock hold time during the iteration
            checks = list(_active_checks)
        for service, check in checks:
            sim = _get_sim(service, check)
            value, ok_fn = sim()
            SLI_VALUE.labels(service=service, check=check).set(value)
            SLI_CHECKS.labels(service=service, check=check).inc()
            if not ok_fn(value):
                SLI_ERRORS.labels(service=service, check=check).inc()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    initial, real = discover_checks(SLO_DIR)
    _init_counters(initial)
    with _lock:
        _active_checks.update(initial)
        _real_configs.update(real)
    real_count = sum(1 for k in initial if k in real)
    print(f"SLI Bridge arrancado — {len(initial)} checks "
          f"({real_count} reales, {len(initial)-real_count} simulados): {sorted(initial)}")
    start_http_server(8000)
    # watch_loop runs as a daemon so it dies automatically if the main process exits
    threading.Thread(target=watch_loop, daemon=True).start()
    sim_loop()
