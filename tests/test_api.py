import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from main import app  # noqa: E402
from starlette.testclient import TestClient

client = TestClient(app)

# ── Shared test data ──────────────────────────────────────────────────────────

ENRICHED_SLO = {
    "name": "latency",
    "slo": "qr-detector-latency",
    "target": 99.0,
    "window": "1h",
    "current": 97.9,
    "status": "breach",
    "error_budget_remaining": 0.0,
}

ENRICHED_SLA = {
    "name": "latency",
    "slo": "qr-detector-sla-latency",
    "target": 95.0,
    "window": "30d",
    "current": 97.0,
    "status": "ok",
    "error_budget_remaining": 40.0,
}

SLO_ENTRIES = [{"slo": "qr-detector-latency", "type": ""}]
SLA_ENTRIES = [{"slo": "qr-detector-sla-latency", "type": "sla"}]


# ── GET /api/services ─────────────────────────────────────────────────────────

def test_get_services_returns_sorted_list():
    # Services are returned alphabetically sorted
    mock_results = [
        {"labels": {"service": "qr-detector"}, "value": 1.0},
        {"labels": {"service": "cv-analyzer"}, "value": 1.0},
    ]
    with patch("main.prom_query_vector", new=AsyncMock(return_value=mock_results)):
        r = client.get("/api/services")
    assert r.status_code == 200
    assert r.json() == {"services": ["cv-analyzer", "qr-detector"]}


def test_get_services_empty_prometheus():
    # Returns empty list when Prometheus has no series
    with patch("main.prom_query_vector", new=AsyncMock(return_value=[])):
        r = client.get("/api/services")
    assert r.status_code == 200
    assert r.json() == {"services": []}


# ── GET /api/slo/{service} ────────────────────────────────────────────────────

def test_get_slo_returns_slos():
    # SLOs are enriched and returned under the correct service
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLO_ENTRIES)), \
         patch("main.enrich", new=AsyncMock(return_value=ENRICHED_SLO)):
        r = client.get("/api/slo/qr-detector")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "qr-detector"
    assert len(data["slos"]) == 1
    assert data["slos"][0]["name"] == "latency"
    assert data["slos"][0]["status"] == "breach"


def test_get_slo_filters_out_slas():
    # SLA entries must not appear in the SLO response
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLA_ENTRIES)):
        r = client.get("/api/slo/qr-detector")
    assert r.status_code == 200
    assert r.json()["slos"] == []


# ── GET /api/sla/{service} ────────────────────────────────────────────────────

def test_get_sla_returns_slas():
    # SLAs are enriched and returned under the correct service
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLA_ENTRIES)), \
         patch("main.enrich", new=AsyncMock(return_value=ENRICHED_SLA)):
        r = client.get("/api/sla/qr-detector")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "qr-detector"
    assert len(data["slas"]) == 1
    assert data["slas"][0]["status"] == "ok"


def test_get_sla_filters_out_slos():
    # SLO entries must not appear in the SLA response
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLO_ENTRIES)):
        r = client.get("/api/sla/qr-detector")
    assert r.status_code == 200
    assert r.json()["slas"] == []


# ── GET /api/history/{service} ────────────────────────────────────────────────

def test_get_history_returns_data_points():
    # Timestamps and values are converted correctly (ratio → percentage)
    history_values = [[1717850000, "0.979"], [1717850060, "0.981"]]
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLO_ENTRIES)), \
         patch("main.prom_query_range", new=AsyncMock(return_value=history_values)):
        r = client.get("/api/history/qr-detector?hours=1")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "qr-detector"
    assert len(data["data"]) == 2
    assert data["data"][0]["timestamp"] == 1717850000
    assert data["data"][0]["value"] == pytest.approx(97.9, rel=1e-2)


def test_get_history_no_slos_returns_empty():
    # Services with no SLOs return an empty data array
    with patch("main.get_slo_entries", new=AsyncMock(return_value=[])):
        r = client.get("/api/history/qr-detector")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_get_history_6h_uses_larger_step():
    # Step grows with the time window to avoid too many data points
    history_values = [[1717828400, "0.990"]]
    with patch("main.get_slo_entries", new=AsyncMock(return_value=SLO_ENTRIES)), \
         patch("main.prom_query_range", new=AsyncMock(return_value=history_values)) as mock_range:
        client.get("/api/history/qr-detector?hours=6")
    _, kwargs = mock_range.call_args
    step = mock_range.call_args[0][3]
    assert step == 360  # max(60, 6*60)


# ── DELETE /api/slo/{slo_name} ────────────────────────────────────────────────

def test_delete_slo_success():
    # YAML and rules files are removed and ok is returned
    with patch("main.SLO_DIR", Path("/fake")), \
         patch("main.PYRRA_RULES_DIR", Path("/fake")), \
         patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "unlink"):
        r = client.delete("/api/slo/qr-detector-latency")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_delete_slo_not_found():
    # Deleting a non-existent SLO returns an error
    with patch("main.SLO_DIR", Path("/fake")), \
         patch.object(Path, "exists", return_value=False):
        r = client.delete("/api/slo/nonexistent")
    assert r.status_code == 200
    assert "error" in r.json()


# ── POST /api/slo/create ──────────────────────────────────────────────────────

def test_create_slo_simulated():
    # Simulated SLO is created with the correct name
    payload = {
        "service": "qr-detector",
        "check": "latency",
        "type": "slo",
        "target": 99.0,
        "window": "1h",
        "mode": "simulated",
    }
    with patch("main.SLO_DIR", Path("/fake")), \
         patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "write_text"):
        r = client.post("/api/slo/create", json=payload)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "qr-detector-latency"}


def test_create_sla_name_includes_sla_segment():
    # SLA names must contain the 'sla' segment for classification
    payload = {
        "service": "qr-detector",
        "check": "latency",
        "type": "sla",
        "target": 95.0,
        "window": "30d",
        "mode": "simulated",
    }
    with patch("main.SLO_DIR", Path("/fake")), \
         patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "write_text"):
        r = client.post("/api/slo/create", json=payload)
    assert r.status_code == 200
    assert r.json()["name"] == "qr-detector-sla-latency"


def test_create_slo_already_exists_returns_error():
    # Creating a duplicate SLO must be rejected
    payload = {"service": "qr-detector", "check": "latency", "mode": "simulated"}
    with patch("main.SLO_DIR", Path("/fake")), \
         patch.object(Path, "exists", return_value=True):
        r = client.post("/api/slo/create", json=payload)
    assert r.status_code == 200
    assert "error" in r.json()


def test_create_slo_empty_service_returns_error():
    # Missing service field must be rejected
    r = client.post("/api/slo/create", json={"service": "", "check": "latency"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_create_slo_empty_check_returns_error():
    # Missing check field must be rejected
    r = client.post("/api/slo/create", json={"service": "qr-detector", "check": ""})
    assert r.status_code == 200
    assert "error" in r.json()


def test_create_slo_real_without_query_returns_error():
    # Real mode requires a PromQL query
    payload = {
        "service": "qr-detector",
        "check": "latency",
        "mode": "real",
        "real_query": "",
    }
    r = client.post("/api/slo/create", json=payload)
    assert r.status_code == 200
    assert "error" in r.json()


def test_create_slo_real_writes_annotations(tmp_path):
    # Real mode writes bridge annotations into the YAML file
    payload = {
        "service": "qr-detector",
        "check": "latency",
        "type": "slo",
        "target": 99.0,
        "window": "1h",
        "mode": "real",
        "real_prometheus_url": "http://host.docker.internal:9090",
        "real_query": 'avg_p_latency{service_type="QR"}',
        "real_threshold": 50.0,
        "real_condition": "<=",
    }
    with patch("main.SLO_DIR", tmp_path), \
         patch.object(Path, "exists", return_value=False):
        r = client.post("/api/slo/create", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    content = (tmp_path / "qr-detector-latency.yaml").read_text()
    assert "bridge.real" in content
    assert "bridge.query" in content
    assert "bridge.threshold" in content


# ── GET /api/prometheus/metrics ───────────────────────────────────────────────

def _make_async_cm(mock_resp):
    # Helper that wraps a mock response in an async context manager
    mock_cm = AsyncMock()
    mock_cm.get = AsyncMock(return_value=mock_resp)
    inst = MagicMock()
    inst.__aenter__ = AsyncMock(return_value=mock_cm)
    inst.__aexit__ = AsyncMock(return_value=False)
    return inst


def test_prometheus_metrics_series_filters_internal_metrics():
    # go_ and process_ prefixed metrics must be excluded from results
    fake_series = [
        {"__name__": "avg_p_latency", "service_type": "QR"},
        {"__name__": "throughput", "service_type": "CV"},
        {"__name__": "go_goroutines"},
        {"__name__": "process_cpu_seconds_total"},
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "success", "data": fake_series}

    with patch("main.httpx.AsyncClient", return_value=_make_async_cm(mock_resp)):
        r = client.get("/api/prometheus/metrics?url=http://fake:9090")

    assert r.status_code == 200
    names = [m["display"] for m in r.json()["metrics"]]
    assert any("avg_p_latency" in n for n in names)
    assert any("throughput" in n for n in names)
    assert not any("go_" in n for n in names)
    assert not any("process_" in n for n in names)


def test_prometheus_metrics_series_includes_label_in_display():
    # Label values appear in the display name to distinguish series
    fake_series = [{"__name__": "avg_p_latency", "service_type": "QR"}]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "success", "data": fake_series}

    with patch("main.httpx.AsyncClient", return_value=_make_async_cm(mock_resp)):
        r = client.get("/api/prometheus/metrics?url=http://fake:9090")

    metric = r.json()["metrics"][0]
    assert "QR" in metric["display"]
    assert 'service_type="QR"' in metric["query"]


def test_prometheus_metrics_fallback_to_label_names():
    # Falls back to label names endpoint when series endpoint returns empty
    empty_resp = MagicMock()
    empty_resp.json.return_value = {"status": "success", "data": []}

    names_resp = MagicMock()
    names_resp.json.return_value = {
        "status": "success",
        "data": ["avg_p_latency", "throughput", "go_gc_duration_seconds"],
    }

    with patch("main.httpx.AsyncClient", side_effect=[
        _make_async_cm(empty_resp),
        _make_async_cm(names_resp),
    ]):
        r = client.get("/api/prometheus/metrics?url=http://fake:9090")

    assert r.status_code == 200
    names = [m["display"] for m in r.json()["metrics"]]
    assert "avg_p_latency" in names
    assert "throughput" in names
    assert "go_gc_duration_seconds" not in names


# ── seconds_to_window unit tests ──────────────────────────────────────────────

def test_seconds_to_window():
    # Converts raw seconds to human-readable window strings
    from main import seconds_to_window
    assert seconds_to_window(3600)   == "1h"
    assert seconds_to_window(86400)  == "1d"
    assert seconds_to_window(2592000) == "30d"
    assert seconds_to_window(60)     == "1m"
    assert seconds_to_window(45)     == "45s"
