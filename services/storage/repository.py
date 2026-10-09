from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from services.sync.schema import NormalizedRow

from .models import Ad, AdAccount, AdSet, Breakdown, Campaign, Creative, DailyMetric, Entity, EntityCurrentState, TrackerMetric


def identity(*parts: str) -> str:
    # Length-prefix avoids ambiguous concatenation across workspaces/providers.
    key = "".join(f"{len(part)}:{part}" for part in parts)
    return str(uuid5(NAMESPACE_URL, key))


def insert_for(session: Session, table):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert(table)
    if dialect == "sqlite":
        return sqlite_insert(table)
    raise RuntimeError("Only PostgreSQL production and SQLite test databases are supported")


def upsert(session: Session, model, values: dict[str, Any], *, update: set[str] | None = None) -> None:
    table = model.__table__
    statement = insert_for(session, table).values(**values)
    primary = [column.name for column in table.primary_key]
    updates = update if update is not None else set(values) - set(primary)
    if updates:
        statement = statement.on_conflict_do_update(index_elements=primary, set_={key: getattr(statement.excluded, key) for key in updates})
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary)
    session.execute(statement)


def save_row(session: Session, workspace: str, provider: str, row: NormalizedRow, observed_at: datetime) -> None:
    account_id = identity(workspace, provider, row.account_id)
    entity_id = identity(account_id, row.kind, row.entity_id)
    account_values = dict(
        id=account_id, workspace_id=workspace, provider=provider, external_id=row.account_id,
        name=row.account_name, currency=row.currency, timezone=row.timezone, observed_at=observed_at,
    )
    upsert(session, AdAccount, account_values, update=set(account_values) - {"id", "name"} | ({"name"} if row.account_name is not None else set()))
    parents = {}
    for parent in row.parents:
        parent_id = identity(account_id, parent.kind, parent.external_id)
        parents[parent.kind] = parent_id
        values = dict(id=parent_id, account_id=account_id, kind=parent.kind, external_id=parent.external_id, name=parent.name)
        upsert(session, Entity, values, update=set(values) - {"id", "name"} | ({"name"} if parent.name is not None else set()))
        link = {"campaign_id": parents.get("campaign")} if parent.kind == "adset" else {}
        upsert(session, {"campaign": Campaign, "adset": AdSet}[parent.kind], {"entity_id": parent_id, **link})
        if parent.state:
            upsert(session, EntityCurrentState, {
                "entity_id": parent_id, **parent.state, "observed_at": observed_at,
                "raw": {key: str(value) if value is not None else None for key, value in parent.state.items()},
            })
    creative_id = None
    if row.creative_id:
        creative_id = identity(account_id, "creative", row.creative_id)
        upsert(session, Entity, dict(id=creative_id, account_id=account_id, kind="creative", external_id=row.creative_id, name=row.creative_name))
        upsert(session, Creative, dict(entity_id=creative_id, media_url=row.media_url))
    entity_values = dict(id=entity_id, account_id=account_id, kind=row.kind, external_id=row.entity_id, name=row.entity_name)
    if row.labels:
        entity_values["labels"] = row.labels
    upsert(session, Entity, entity_values, update=set(entity_values) - {"id", "name"} | ({"name"} if row.entity_name is not None else set()))
    links = {}
    if row.kind == "adset" and "campaign" in parents:
        links["campaign_id"] = parents["campaign"]
    if row.kind == "ad":
        if "adset" in parents:
            links["adset_id"] = parents["adset"]
        if creative_id:
            links["creative_id"] = creative_id
    upsert(session, {"campaign": Campaign, "adset": AdSet, "ad": Ad}[row.kind], {"entity_id": entity_id, **links})
    if row.state:
        upsert(session, EntityCurrentState, {
            "entity_id": entity_id, **row.state, "observed_at": observed_at,
            "raw": {key: str(value) if value is not None else None for key, value in row.state.items()},
        })
    if row.dimensions is not None:
        key = sha256(json.dumps(row.dimensions, sort_keys=True).encode()).hexdigest()
        upsert(session, Breakdown, {
            "entity_id": entity_id, "day": row.day, "source": provider, "dimension_key": key,
            "dimensions": row.dimensions, "observed_at": observed_at,
            "metrics": {"currency": row.currency, "timezone": row.timezone, **{
                name: str(value) if isinstance(value, Decimal) else value for name, value in row.metrics.items()
            }},
        })
        return
    upsert(session, DailyMetric, {
        "entity_id": entity_id, "day": row.day, "source": provider,
        "currency": row.currency, "timezone": row.timezone,
        **row.metrics, "observed_at": observed_at, "raw": row.raw,
    })
    if row.tracker is not None:
        upsert(session, TrackerMetric, {
            "entity_id": entity_id, "day": row.day, "source": provider,
            "currency": row.tracker_currency, "timezone": row.timezone,
            **row.tracker, "observed_at": observed_at, "raw": row.raw,
        })
    elif row.tracker_present is False:
        session.execute(delete(TrackerMetric).where(
            TrackerMetric.entity_id == entity_id, TrackerMetric.day == row.day,
            TrackerMetric.source == provider,
        ))
