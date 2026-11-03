from fastapi import Header, HTTPException

from . import config


def require_key(x_api_key: str | None = Header(default=None)):
    """API_KEY o'rnatilgan bo'lsa, `X-API-Key` sarlavhasi talab qilinadi."""
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(401, "API kalit noto'g'ri yoki yo'q")
