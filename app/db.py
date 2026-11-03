from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import DATABASE_URL

# PostgreSQL uchun connection pool (150 talaba)
_args = {}
_pool_kw = {}
if DATABASE_URL.startswith("sqlite"):
    _args = {"check_same_thread": False}
else:
    _pool_kw = {"pool_size": 20, "max_overflow": 30, "pool_timeout": 30, "pool_pre_ping": True}

engine = create_engine(DATABASE_URL, connect_args=_args, **_pool_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
