# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INVOICES_DIR = BASE_DIR / "invoices"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name, str(default)) or "").strip()
    try:
        return max(0, int(raw))
    except Exception:
        return default


def _delete_old_files(folder: Path, days: int) -> int:
    if not folder.exists() or days <= 0:
        return 0
    cut = datetime.now() - timedelta(days=days)
    deleted = 0
    for p in folder.glob("**/*"):
        if not p.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if mtime < cut:
                p.unlink(missing_ok=True)
                deleted += 1
        except Exception:
            continue
    return deleted


def _anonymize_audit(days: int) -> int:
    audit = LOGS_DIR / "audit.jsonl"
    if not audit.exists() or days <= 0:
        return 0
    cut = datetime.now() - timedelta(days=days)
    changed = 0
    out = []
    for ln in audit.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        ts = rec.get("ts", "")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            out.append(rec)
            continue
        if dt < cut and rec.get("user_id") is not None:
            rec["user_id"] = None
            rec["user_anon"] = True
            changed += 1
        out.append(rec)
    with audit.open("w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return changed


def _prune_idempotency(days: int) -> int:
    if days <= 0:
        return 0
    cut = datetime.now() - timedelta(days=days)
    total_removed = 0
    for name in ("file_hash_index.json", "content_hash_index.json"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kept = {}
        for k, v in data.items():
            ts = str(v.get("ts", ""))
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                kept[k] = v
                continue
            if dt >= cut:
                kept[k] = v
            else:
                total_removed += 1
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return total_removed


def apply_retention() -> dict:
    inv_days = _env_int("RETENTION_INVOICE_DAYS", 365)
    log_days = _env_int("RETENTION_LOG_DAYS", 90)
    anon_days = _env_int("RETENTION_AUDIT_ANON_DAYS", 30)
    idem_days = _env_int("RETENTION_IDEMPOTENCY_DAYS", 180)

    return {
        "deleted_invoices": _delete_old_files(INVOICES_DIR, inv_days),
        "deleted_logs": _delete_old_files(LOGS_DIR, log_days),
        "anonymized_audit_rows": _anonymize_audit(anon_days),
        "pruned_idempotency_rows": _prune_idempotency(idem_days),
    }
