from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
# The API process and the MCP tool server share this file: WAL lets readers run during a write,
# and the busy timeout makes a writer wait for the other process instead of failing.
engine = create_engine(settings.db_url, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
