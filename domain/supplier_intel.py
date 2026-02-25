# -*- coding: utf-8 -*-
import json
from config import DATA_DIR

SUPPLIERS_FILE = DATA_DIR / "known_suppliers.json"

def remember_supplier(nip: str, name: str, category: str):
    """Learns supplier details to automate future processing."""
    if not nip: return
    
    data = {}
    if SUPPLIERS_FILE.exists():
        try:
            data = json.loads(SUPPLIERS_FILE.read_text(encoding="utf-8"))
        except: pass
        
    data[nip] = {
        "name": name,
        "category": category,
        "last_seen": json.dumps(True, default=str) # simplified
    }
    SUPPLIERS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def get_supplier_info(nip: str) -> dict | None:
    """Retrieves learned info about a supplier."""
    if not nip or not SUPPLIERS_FILE.exists(): return None
    try:
        data = json.loads(SUPPLIERS_FILE.read_text(encoding="utf-8"))
        return data.get(nip)
    except: return None
