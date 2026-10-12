"""One-time private service DB role; password is read from a mounted secret only."""

from __future__ import annotations

import os
from pathlib import Path

from psycopg import Error, sql
from sqlalchemy.exc import SQLAlchemyError

from services.storage.database import make_engine


def main():
    engine = make_engine()
    try:
        password = Path("/run/secrets/credential_db_password").read_text().strip()
        if len(password) < 32:
            raise ValueError("INVALID_SERVICE_PASSWORD")
        connection = engine.raw_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname='mcc_credential_manager'"
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        sql.SQL(
                            "CREATE ROLE mcc_credential_manager LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                        ).format(sql.Literal(password))
                    )
                cursor.execute(
                    sql.SQL(
                        "GRANT CONNECT ON DATABASE {} TO mcc_credential_manager"
                    ).format(
                        sql.Identifier(os.environ.get("POSTGRES_DB", "metric_control"))
                    )
                )
                cursor.execute("GRANT USAGE ON SCHEMA public TO mcc_credential_manager")
                cursor.execute(
                    "GRANT SELECT ON users,user_sessions,provider_connections,write_credential_states,api_quotas TO mcc_credential_manager"
                )
                cursor.execute(
                    "GRANT INSERT,UPDATE ON write_credential_states,api_quotas TO mcc_credential_manager"
                )
                cursor.execute(
                    "GRANT INSERT ON write_credential_audit TO mcc_credential_manager"
                )
            connection.commit()
        finally:
            connection.close()
        print("CREDENTIAL_SERVICE_ROLE: READY")
        return 0
    except (OSError, ValueError, Error, SQLAlchemyError):
        print("CREDENTIAL_SERVICE_ROLE: FAILED")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
