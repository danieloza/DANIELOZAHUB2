# -*- coding: utf-8 -*-
import json
from datetime import datetime

from config import DATA_DIR

_INDEX_FILE = DATA_DIR / "file_hash_index.json"
_CONTENT_INDEX_FILE = DATA_DIR / "content_hash_index.json"


def _load_index(path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _stamp(row_no: int, file_link: str = "", user_id: int | None = None) -> dict:
    return {
        "row_no": row_no,
        "file_link": file_link,
        "user_id": user_id,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def find_duplicate(file_hash: str):
    if not file_hash:
        return None
    return _load_index(_INDEX_FILE).get(file_hash)


def register_file_hash(file_hash: str, row_no: int, file_link: str = "", user_id: int | None = None):
    if not file_hash:
        return
    data = _load_index(_INDEX_FILE)
    data[file_hash] = _stamp(row_no=row_no, file_link=file_link, user_id=user_id)
    _save_index(_INDEX_FILE, data)


def find_duplicate_content(content_hash: str):
    if not content_hash:
        return None
    return _load_index(_CONTENT_INDEX_FILE).get(content_hash)


def register_content_hash(content_hash: str, row_no: int, file_link: str = "", user_id: int | None = None):
    if not content_hash:
        return
    data = _load_index(_CONTENT_INDEX_FILE)
    data[content_hash] = _stamp(row_no=row_no, file_link=file_link, user_id=user_id)
    _save_index(_CONTENT_INDEX_FILE, data)
