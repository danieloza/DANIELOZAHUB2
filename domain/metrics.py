# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

from config import DATA_DIR

_EVENTS_FILE = DATA_DIR / "metrics_events.jsonl"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append(rec: dict) -> None:
    with _EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record_metric(name: str, ok: bool = True, latency_ms: int | None = None, **tags) -> None:
    rec = {"ts": _now(), "name": name, "ok": bool(ok), "latency_ms": latency_ms, **tags}
    _append(rec)


def _read_last_hours(hours: int = 24) -> list[dict]:
    if not _EVENTS_FILE.exists():
        return []
    cut = datetime.now() - timedelta(hours=hours)
    out = []
    for ln in _EVENTS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-50000:]:
        try:
            rec = json.loads(ln)
            ts = datetime.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S")
            if ts >= cut:
                out.append(rec)
        except Exception:
            continue
    return out


def _p95(vals: list[int]) -> int:
    if not vals:
        return 0
    arr = sorted(vals)
    idx = int(0.95 * (len(arr) - 1))
    return arr[idx]


def summarize_24h() -> dict:
    ev = _read_last_hours(24)
    ocr = [r for r in ev if r.get("name") == "ocr_process"]
    ocr_lat = [int(r.get("latency_ms", 0) or 0) for r in ocr if r.get("latency_ms") is not None]
    ocr_ok = sum(1 for r in ocr if r.get("ok"))
    err_24h = sum(1 for r in ev if not r.get("ok", True))

    return {
        "events_24h": len(ev),
        "errors_24h": err_24h,
        "ocr_total_24h": len(ocr),
        "ocr_ok_24h": ocr_ok,
        "ocr_success_rate": round((ocr_ok / len(ocr) * 100.0), 2) if ocr else 0.0,
        "ocr_latency_avg_ms": int(sum(ocr_lat) / len(ocr_lat)) if ocr_lat else 0,
        "ocr_latency_p95_ms": _p95(ocr_lat),
    }
