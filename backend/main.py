from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
import time
from pathlib import Path
from typing import Optional

app = FastAPI()

# Allow all origins so the React frontend can call the API from any port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROMETHEUS_URL  = "http://prometheus:9090"
SLO_DIR         = Path(os.getenv("SLO_DIR",         "/definitions"))
PYRRA_RULES_DIR = Path(os.getenv("PYRRA_RULES_DIR", "/pyrra-rules"))


def seconds_to_window(s: float) -> str:
    # Converts a raw seconds value returned by pyrra_window into a human-readable string
    s = int(s)
    if s % 86400 == 0: return f"{s // 86400}d"
    if s % 3600  == 0: return f"{s // 3600}h"
    if s % 60    == 0: return f"{s // 60}m"
    return f"{s}s"


async def prom_query(query: str) -> Optional[float]:
    # Executes an instant PromQL query and returns the first scalar result
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
        d = r.json()
        if d["status"] == "success" and d["data"]["result"]:
            return float(d["data"]["result"][0]["value"][1])
    return None


async def prom_query_vector(query: str) -> list:
    # Executes an instant PromQL query and returns all result series with their labels
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
        d = r.json()
        if d["status"] == "success":
            return [
                {"labels": item["metric"], "value": float(item["value"][1])}
                for item in d["data"]["result"]
            ]
    return []


async def prom_query_range(query: str, start: int, end: int, step: int):
    # Executes a range PromQL query and returns a list of [timestamp, value] pairs
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": f"{step}s"},
        )
        d = r.json()
        if d["status"] == "success" and d["data"]["result"]:
            return d["data"]["result"][0]["values"]
    return []


async def get_slo_entries(service: str) -> list[dict]:
    # Queries Prometheus for all active SLO/SLA names of a service and classifies each as slo or sla
    q = (
        f'group by(slo) ('
        f'{{__name__=~"sli_checks:increase.+",service="{service}"}} or '
        f'{{__name__=~"http_requests:increase.+",service="{service}"}})'
    )
    results = await prom_query_vector(q)
    seen, entries = set(), []
    for r in results:
        slo = r["labels"].get("slo", "")
        if slo and slo not in seen:
            seen.add(slo)
            # SLAs are identified by the segment "sla" in the dash-separated name
            is_sla = "sla" in slo.split("-")
            entries.append({"slo": slo, "type": "sla" if is_sla else ""})
    return entries


async def enrich(service: str, slo_name: str) -> dict:
    # Queries pyrra_objective, pyrra_window and pyrra_availability and computes status and error budget
    target_raw = await prom_query(f'pyrra_objective{{slo="{slo_name}"}}')
    window_raw = await prom_query(f'pyrra_window{{slo="{slo_name}"}}')
    avail_raw  = await prom_query(f'pyrra_availability{{slo="{slo_name}"}}')

    target  = round(target_raw * 100, 1) if target_raw is not None else None
    window  = seconds_to_window(window_raw) if window_raw is not None else None
    current = round(avail_raw * 100, 3)    if avail_raw  is not None else None

    budget = None
    if current is not None and target is not None:
        allowed = 100 - target
        actual  = 100 - current
        budget  = round(max(0.0, (allowed - actual) / allowed * 100), 1) if allowed > 0 else 100.0

    # Short name: strips the service prefix and the "sla-" segment if present
    short = slo_name.replace(f"{service}-", "").replace("sla-", "")

    return {
        "name":                   short,
        "slo":                    slo_name,
        "target":                 target,
        "window":                 window,
        "current":                current,
        "status":                 "ok" if (current is not None and target is not None and current >= target) else "breach",
        "error_budget_remaining": budget,
    }


@app.get("/api/services")
async def get_services():
    # Returns a sorted list of all services that have at least one active recording rule or counter
    results = await prom_query_vector(
        'group by(service) ('
        '{__name__=~"sli_checks:increase.+"} or '
        '{__name__=~"http_requests:increase.+"} or '
        'sli_checks_total)'
    )
    services = sorted({r["labels"]["service"] for r in results if "service" in r["labels"]})
    return {"services": services}


@app.get("/api/slo/{service}")
async def get_slo(service: str):
    # Returns all SLOs (non-SLA entries) for the given service, enriched with Pyrra metrics
    entries   = await get_slo_entries(service)
    slo_names = [e["slo"] for e in entries if e["type"] != "sla"]
    slos = [await enrich(service, name) for name in slo_names]
    return {"service": service, "slos": slos}


@app.get("/api/sla/{service}")
async def get_sla(service: str):
    # Returns all SLAs for the given service, enriched with Pyrra metrics
    entries   = await get_slo_entries(service)
    sla_names = [e["slo"] for e in entries if e["type"] == "sla"]
    slas = [await enrich(service, name) for name in sla_names]
    return {"service": service, "slas": slas}


@app.get("/api/history/{service}")
async def get_history(service: str, hours: int = 1):
    # Returns time-series availability data for the chart using pyrra_errors/requests rate5m
    entries   = await get_slo_entries(service)
    slo_names = [e["slo"] for e in entries if e["type"] != "sla"]
    if not slo_names:
        return {"service": service, "data": []}

    # Use the first SLO alphabetically as representative for the service history
    slo_name = slo_names[0]
    end   = int(time.time())
    start = end - hours * 3600
    # Grow the step with the window to keep the number of chart points manageable
    step  = max(60, hours * 60)
    q = (
        f'1 - pyrra_errors:rate5m{{slo="{slo_name}"}}'
        f' / pyrra_requests:rate5m{{slo="{slo_name}"}}'
    )
    values = await prom_query_range(q, start, end, step)
    return {
        "service": service,
        "data": [{"timestamp": int(v[0]), "value": round(float(v[1]) * 100, 3)} for v in values],
    }


@app.delete("/api/slo/{slo_name}")
async def delete_slo(slo_name: str):
    # Removes the YAML definition and generated rules, then triggers a Prometheus reload
    slo_path   = SLO_DIR / f"{slo_name}.yaml"
    rules_path = PYRRA_RULES_DIR / f"{slo_name}.yaml"

    if not slo_path.exists():
        return {"error": f"No existe el SLO '{slo_name}'"}

    slo_path.unlink()
    if rules_path.exists():
        rules_path.unlink()

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{PROMETHEUS_URL}/-/reload")
    except Exception:
        pass

    return {"ok": True}


@app.get("/api/prometheus/metrics")
async def get_prometheus_metrics(url: str):
    # Discovers available metrics on an external Prometheus instance for the creation form
    SKIP_LABELS   = {"__name__", "instance", "job", "container_id", "metric_id"}
    SKIP_PREFIXES = ("go_", "process_", "prometheus_", "scrape_", "up", "ALERTS", "net_")

    async def fetch_series() -> list[dict]:
        # Primary path: /api/v1/series returns series with their full label sets
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{url}/api/v1/series", params={"match[]": '{__name__=~".+"}'})
            d = r.json()
            if d.get("status") == "success":
                return d.get("data", [])
        return []

    async def fetch_names() -> list[str]:
        # Fallback path: /api/v1/label/__name__/values returns metric names only
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{url}/api/v1/label/__name__/values")
            d = r.json()
            if d.get("status") == "success":
                return d.get("data", [])
        return []

    series = await fetch_series()

    if series:
        seen, metrics = set(), []
        for s in series:
            name = s.get("__name__", "")
            if not name or any(name.startswith(p) for p in SKIP_PREFIXES):
                continue
            key_labels = {k: v for k, v in s.items() if k not in SKIP_LABELS}
            label_str  = ", ".join(f'{k}="{v}"' for k, v in sorted(key_labels.items()))
            query      = f'{name}{{{label_str}}}' if label_str else name
            # Include label values in the display name to distinguish series of the same metric
            display    = f"{name}  ({', '.join(key_labels.values())})" if key_labels else name
            if query not in seen:
                seen.add(query)
                metrics.append({"display": display, "query": query})
        return {"metrics": sorted(metrics, key=lambda x: x["display"])}

    names = await fetch_names()
    filtered = [n for n in names if not any(n.startswith(p) for p in SKIP_PREFIXES)]
    return {"metrics": [{"display": n, "query": n} for n in sorted(filtered)]}


class SLOCreateRequest(BaseModel):
    service: str
    check: str
    type: str = "slo"
    target: float = 99.0
    window: str = "1h"
    description: str = ""
    mode: str = "simulated"
    real_prometheus_url: str = "http://host.docker.internal:9090"
    real_query: str = ""
    real_threshold: Optional[float] = None
    real_condition: str = "<="


@app.post("/api/slo/create")
async def create_slo(req: SLOCreateRequest):
    # Validates the request and writes a Pyrra-compatible YAML file to /definitions/
    service  = req.service.strip().lower()
    check    = req.check.strip().lower()
    slo_type = req.type.lower()

    if not service or not check:
        return {"error": "service y check son obligatorios"}

    if req.mode == "real" and not req.real_query:
        return {"error": "La query PromQL es obligatoria para métricas reales"}

    # SLA names include the "sla" segment so get_slo_entries can classify them
    name = f"{service}-sla-{check}" if slo_type == "sla" else f"{service}-{check}"
    path = SLO_DIR / f"{name}.yaml"

    if path.exists():
        return {"error": f"Ya existe un SLO con el nombre '{name}'"}

    target_str  = str(int(req.target)) if req.target == int(req.target) else str(req.target)
    description = req.description or f"{check} de {service}: {target_str}% en ventana {req.window}"

    annotations_block = ""
    if req.mode == "real":
        # Store real-metric config as YAML annotations so the SLI Bridge can read it
        q = req.real_query.replace("'", "''")
        annotations_block = (
            f"  annotations:\n"
            f"    bridge.real: \"true\"\n"
            f"    bridge.prometheus_url: \"{req.real_prometheus_url}\"\n"
            f"    bridge.query: '{q}'\n"
            f"    bridge.threshold: \"{req.real_threshold}\"\n"
            f"    bridge.condition: \"{req.real_condition}\"\n"
        )

    content = (
        f"apiVersion: pyrra.dev/v1alpha1\n"
        f"kind: ServiceLevelObjective\n"
        f"metadata:\n"
        f"  name: {name}\n"
        f"  labels:\n"
        f"    service: {service}\n"
        f"{annotations_block}"
        f"spec:\n"
        f'  description: "{description}"\n'
        f"  target: \"{target_str}\"\n"
        f"  window: {req.window}\n"
        f"  indicator:\n"
        f"    ratio:\n"
        f"      errors:\n"
        f'        metric: sli_errors_total{{service="{service}", check="{check}"}}\n'
        f"      total:\n"
        f'        metric: sli_checks_total{{service="{service}", check="{check}"}}\n'
    )

    try:
        path.write_text(content)
        return {"ok": True, "name": name}
    except Exception as e:
        return {"error": str(e)}
