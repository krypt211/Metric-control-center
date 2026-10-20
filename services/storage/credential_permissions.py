"""Least-privilege SQL grants for the private credential/pilot service."""

from __future__ import annotations

from psycopg import Cursor, sql

ROLE = "mcc_credential_manager"
READ_TABLES = (
    "users",
    "user_sessions",
    "provider_connections",
    "write_credential_states",
    "api_quotas",
    "ad_accounts",
    "entities",
    "campaigns",
    "adsets",
    "ads",
    "entity_current_state",
    "provider_account_mappings",
    "provider_routing_settings",
    "manual_action_grants",
    "action_requests",
    "action_executions",
    "action_logs",
)


def grant_credential_access(
    cursor: Cursor, *, schema: str = "public", role: str = ROLE
) -> None:
    """Grant durable pilot access without write access to advertising facts or roles.

    PostgreSQL row locks require UPDATE on at least one column. Only the ID
    columns used by existing actor/entity locking are granted, not role, name,
    status, credential, hierarchy, or economic fields. No DELETE or DDL grants.
    Identifiers are quoted even in isolated fixture schemas.
    """
    target = sql.Identifier(role)
    cursor.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), target)
    )
    groups = (
        ("SELECT", READ_TABLES),
        (
            "INSERT, UPDATE",
            ("write_credential_states", "api_quotas", "action_executions"),
        ),
        ("INSERT", ("write_credential_audit", "action_logs")),
        ("UPDATE", ("action_requests",)),
        ("UPDATE (id)", ("users", "entities")),
    )
    for privileges, tables in groups:
        cursor.execute(
            sql.SQL("GRANT {} ON {} TO {}").format(
                sql.SQL(privileges),
                sql.SQL(", ").join(sql.Identifier(schema, table) for table in tables),
                target,
            )
        )
