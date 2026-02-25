# -*- coding: utf-8 -*-
import json
from pathlib import Path
from config import DATA_DIR

PREFS_FILE = DATA_DIR / "user_prefs.json"

def _load_prefs() -> dict:
    if not PREFS_FILE.exists():
        return {}
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except:
        return {}

def _save_prefs(prefs: dict):
    PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")

def get_user_pref(uid: int, key: str, default=None):
    prefs = _load_prefs()
    user_prefs = prefs.get(str(uid), {})
    return user_prefs.get(key, default)

def set_user_pref(uid: int, key: str, value):
    prefs = _load_prefs()
    if str(uid) not in prefs:
        prefs[str(uid)] = {}
    prefs[str(uid)][key] = value
    _save_prefs(prefs)

def apply_prefs_to_state(uid: int, state: dict):
    """Syncs persisted preferences into the runtime state."""
    state["large_font"] = get_user_pref(uid, "large_font", False)
    state["voice_mode"] = get_user_pref(uid, "voice_mode", False)
    return state
