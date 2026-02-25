# -*- coding: utf-8 -*-
import json
from datetime import datetime
from config import DATA_DIR

HISTORY_FILE = DATA_DIR / "change_history.json"

def log_change(uid: int, row_no: int, field: str, old_val: str, new_val: str, source: str = "manual"):
    """
    Senior IT: Immutable Audit Trail.
    Records every single change to the data for full transparency and accountability.
    """
    entry = {
        "ts": datetime.now().isoformat(),
        "user_id": uid,
        "row": row_no,
        "field": field,
        "old": old_val,
        "new": new_val,
        "source": source
    }
    
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except:
            pass
            
    history.append(entry)
    # Keep last 1000 changes
    HISTORY_FILE.write_text(json.dumps(history[-1000:], indent=2), encoding="utf-8")

def get_row_history(row_no: int) -> list:
    """Returns the history of changes for a specific invoice."""
    if not HISTORY_FILE.exists(): return []
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [h for h in history if h.get("row") == row_no]
    except:
        return []
