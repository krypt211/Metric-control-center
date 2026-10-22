from sqlalchemy import event
from sqlalchemy.engine import Engine


# Test databases are throwaway files: skip fsync on every SQLite commit.
# Transaction semantics inside the process are unchanged.
@event.listens_for(Engine, "connect")
def fast_sqlite(connection, _):
    if type(connection).__module__.startswith("sqlite3"):
        connection.execute("PRAGMA synchronous=OFF")
