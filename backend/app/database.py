from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
import os

from app.config import settings

db_url = settings.DATABASE_URL
_sqlite = db_url.startswith("sqlite")

_engine_kwargs = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
} if not _sqlite else {
    "connect_args": {"check_same_thread": False},
}
if not _sqlite:
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_engine(db_url, **_engine_kwargs)

if _sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
