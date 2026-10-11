from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .db import Base, SessionLocal, engine
from .deps import require_key
from .routers import analytics, events, exams, sessions, students


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    from .seed import seed_if_empty
    with SessionLocal() as db:
        seed_if_empty(db)
    yield


app = FastAPI(title="AiTECH Proctoring API", version="1.0.0", lifespan=lifespan,
              description="LMS va tashqi tizimlar uchun oddiy, ochiq interfeys.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

for r in (sessions.router, students.router, exams.router, analytics.router, events.router):
    app.include_router(r, prefix="/api/v1", dependencies=[Depends(require_key)])


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
