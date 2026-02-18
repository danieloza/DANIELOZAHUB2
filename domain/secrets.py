# -*- coding: utf-8 -*-
import os
import time
from threading import Lock


_CACHE: dict[str, tuple[float, str]] = {}
_LOCK = Lock()


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _cache_ttl_sec() -> int:
    raw = _env("SECRET_CACHE_TTL_SEC", "300")
    try:
        return max(0, int(raw))
    except Exception:
        return 300


def _provider() -> str:
    return _env("SECRET_PROVIDER", "env").lower() or "env"


def _fetch_from_gcp(secret_name: str) -> str:
    from google.cloud import secretmanager  # type: ignore

    project_id = _env("GCP_PROJECT_ID", "")
    if not project_id:
        raise RuntimeError("Missing GCP_PROJECT_ID for SECRET_PROVIDER=gcp_secret_manager")
    version = _env("SECRET_VERSION", "latest") or "latest"
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
    response = client.access_secret_version(request={"name": path})
    return response.payload.data.decode("utf-8").strip()


def resolve_secret_ref(raw_value: str) -> str:
    raw = (raw_value or "").strip()
    if not raw.startswith("sm://"):
        return raw
    secret_name = raw.removeprefix("sm://").strip()
    if not secret_name:
        return ""
    provider = _provider()
    if provider == "gcp_secret_manager":
        return _fetch_from_gcp(secret_name)
    # env provider: map sm://MY_SECRET to env MY_SECRET
    return _env(secret_name, "")


def secret_env(name: str, default: str = "") -> str:
    raw = _env(name, default)
    if not raw.startswith("sm://"):
        return raw

    ttl = _cache_ttl_sec()
    now = time.time()
    if ttl > 0:
        with _LOCK:
            hit = _CACHE.get(raw)
            if hit and now < hit[0]:
                return hit[1]

    val = resolve_secret_ref(raw)
    if ttl > 0:
        with _LOCK:
            _CACHE[raw] = (now + ttl, val)
    return val
