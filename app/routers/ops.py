"""/api/exam/admin/ops — "Baza" paneli: Neon (Postgres) holatini ko'rsatadi.

Ixtiyoriy: .env da NEON_API_KEY/NEON_PROJECT_ID bo'lmasa, "sozlanmagan" deb
qaytariladi — hech narsa buzilmaydi. Haqiqiy Neon API'ga so'rov faqat shu bo'lim
ochilganda, 30 soniyalik keshlash bilan yuboriladi (API'ni ortiqcha bezovta
qilmaslik uchun).
"""
import time

import httpx
from fastapi import APIRouter, Header

from .. import config
from .exam import _check_superadmin, _db

router = APIRouter(prefix="/api/exam/admin/ops", tags=["ops"])

_CACHE_TTL = 30
_cache: dict = {"at": 0, "data": None}

NEON_BASE = "https://console.neon.tech/api/v2"


def _fetch_neon() -> dict:
    if not config.NEON_API_KEY or not config.NEON_PROJECT_ID:
        return {"configured": False}
    headers = {"Authorization": f"Bearer {config.NEON_API_KEY}", "Accept": "application/json"}
    pid = config.NEON_PROJECT_ID
    try:
        with httpx.Client(timeout=10) as client:
            proj_r = client.get(f"{NEON_BASE}/projects/{pid}", headers=headers)
            proj_r.raise_for_status()
            proj = proj_r.json().get("project", {})

            branches_r = client.get(f"{NEON_BASE}/projects/{pid}/branches", headers=headers)
            branches = branches_r.json().get("branches", []) if branches_r.status_code == 200 else []

            endpoints_r = client.get(f"{NEON_BASE}/projects/{pid}/endpoints", headers=headers)
            endpoints = endpoints_r.json().get("endpoints", []) if endpoints_r.status_code == 200 else []

            databases_r = client.get(f"{NEON_BASE}/projects/{pid}/databases", headers=headers)
            databases = databases_r.json().get("databases", []) if databases_r.status_code == 200 else []

            ops_r = client.get(f"{NEON_BASE}/projects/{pid}/operations", headers=headers, params={"limit": 15})
            operations = ops_r.json().get("operations", []) if ops_r.status_code == 200 else []

        return {
            "configured": True,
            "error": None,
            "project": {
                "id": proj.get("id"),
                "name": proj.get("name"),
                "region_id": proj.get("region_id"),
                "pg_version": proj.get("pg_version"),
                "created_at": proj.get("created_at"),
                "updated_at": proj.get("updated_at"),
                "proxy_host": proj.get("proxy_host"),
                # Joriy hisob-kitob davri uchun foydalanish (bepul rejada ham ishlaydi):
                "data_storage_bytes_hour": proj.get("data_storage_bytes_hour"),
                "data_transfer_bytes": proj.get("data_transfer_bytes"),
                "written_data_bytes": proj.get("written_data_bytes"),
                "compute_time_seconds": proj.get("compute_time_seconds"),
                "active_time_seconds": proj.get("active_time_seconds"),
                "synthetic_storage_size": proj.get("synthetic_storage_size"),
                "branch_logical_size_limit_bytes": proj.get("branch_logical_size_limit_bytes"),
                "store_passwords": proj.get("store_passwords"),
            },
            "branches": [
                {"id": b.get("id"), "name": b.get("name"), "default": b.get("default"), "primary": b.get("primary"),
                 "protected": b.get("protected"), "current_state": b.get("current_state"),
                 "logical_size": b.get("logical_size"), "created_at": b.get("created_at")}
                for b in branches
            ],
            "endpoints": [
                {"type": e.get("type"), "host": e.get("host"), "current_state": e.get("current_state"),
                 "autoscaling_limit_min_cu": e.get("autoscaling_limit_min_cu"),
                 "autoscaling_limit_max_cu": e.get("autoscaling_limit_max_cu"),
                 "suspend_timeout_seconds": e.get("suspend_timeout_seconds")}
                for e in endpoints
            ],
            "databases": [
                {"name": d.get("name"), "owner_name": d.get("owner_name"), "branch_id": d.get("branch_id"),
                 "created_at": d.get("created_at")}
                for d in databases
            ],
            "operations": [
                {"action": o.get("action"), "status": o.get("status"), "created_at": o.get("created_at"),
                 "total_duration_ms": o.get("total_duration_ms")}
                for o in operations
            ],
        }
    except httpx.HTTPStatusError as e:
        return {"configured": True, "error": f"Neon API xatosi: {e.response.status_code}"}
    except httpx.HTTPError as e:
        return {"configured": True, "error": f"Neon bilan bog'lanib bo'lmadi: {e}"}


@router.get("/status")
def ops_status(x_teacher_login: str | None = Header(None), x_teacher_password: str | None = Header(None)):
    with _db() as db:
        _check_superadmin(db, x_teacher_login, x_teacher_password)

    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    data = {"neon": _fetch_neon(), "cached_at": int(now)}
    _cache["data"] = data
    _cache["at"] = now
    return data
