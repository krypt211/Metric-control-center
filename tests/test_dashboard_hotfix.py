"""Dashboard hotfix regressions use isolated SQLite facts, never live credentials."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from test_sync import StorageFixture, config, row

from services.analytics.dashboard import dashboard_today
from services.analytics.table import Filters, table_data
from services.providers.models import ProviderConnection, ProviderWindow
from services.providers.presentation import quota_numbers
from services.providers.router import DataSourceRouter
from services.storage.models import AdAccount, DailyMetric, SyncRun
from services.storage.repository import save_row
from services.sync.schema import InsightSchema

DAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 0, 30, tzinfo=UTC)


@pytest.fixture
def store():
    fixture = StorageFixture()
    fixture.setUp()
    try:
        yield fixture.sessions
    finally:
        fixture.tearDown()


def seed(store, *, zone: str = "Europe/Kiev", day: date = DAY) -> str:
    """Create one proven account/ad fact in the private test database."""
    raw = row(day=str(day), spend="0")
    raw["account"]["timezone"] = zone
    normalized = InsightSchema(config()).row(raw)
    with store.begin() as session:
        save_row(session, "default", "metricflow", normalized, NOW)
        account = session.scalar(select(AdAccount))
        account_id = account.id
        session.add(
            ProviderConnection(
                workspace_id="default",
                provider="metricflow",
                enabled=True,
                credential_source="server",
                revision=1,
                status="healthy",
                config={},
                permissions={},
                capabilities={},
                quota={},
                updated_at=NOW,
            )
        )
    return account_id


def add_window(store, account_id: str, *, complete: bool, revision: int = 1):
    with store.begin() as session:
        session.add(
            SyncRun(
                id="test-run",
                workspace_id="default",
                provider="metricflow",
                job="today",
                status="succeeded",
                start_day=DAY,
                end_day=DAY,
                started_at=NOW,
                finished_at=NOW,
                rows=0,
                pages=1,
                requests=1,
            )
        )
        session.flush()
        session.add(
            ProviderWindow(
                account_id=account_id,
                start_day=DAY,
                end_day=DAY,
                complete=complete,
                credential_revision=revision,
                imported_at=NOW,
                run_id="test-run",
            )
        )


def test_catalog_account_without_facts_has_null_metrics(store):
    seed(store, day=DAY - timedelta(days=1))
    with store() as session:
        result = table_data(session, "default", Filters(DAY, DAY))
        assert result["total"] == 1
        assert result["rows"][0]["spend"] is None
        assert result["rows"][0]["clicks"] is None
        assert result["rows"][0]["has_facts"] is False
        assert (
            table_data(session, "default", Filters(DAY, DAY), level="ad")["total"] == 0
        )
        assert (
            table_data(session, "default", Filters(DAY, DAY, ad="missing"))["total"]
            == 0
        )


def test_true_zero_is_retained_and_history_not_duplicated(store):
    seed(store, day=DAY - timedelta(days=1))
    with store() as session:
        result = table_data(session, "default", Filters(DAY - timedelta(days=6), DAY))
        assert result["total"] == 1
        assert float(result["rows"][0]["spend"]) == 0
        assert result["rows"][0]["has_facts"] is True
        assert len(session.scalars(select(DailyMetric)).all()) == 1


@pytest.mark.parametrize("complete,revision", [(False, 1), (True, 2)])
def test_incomplete_or_wrong_revision_facts_are_not_published(
    store, complete, revision
):
    account_id = seed(store)
    add_window(store, account_id, complete=complete, revision=revision)
    with store() as session:
        result = table_data(session, "default", Filters(DAY, DAY))
        assert result["rows"][0]["spend"] is None
        assert result["rows"][0]["has_facts"] is False
        assert (
            table_data(session, "default", Filters(DAY, DAY), level="ad")["total"] == 0
        )
        route = next(
            iter(DataSourceRouter(session, "default", NOW).resolve(DAY, DAY).values())
        )
        assert route["connection"] == "healthy"
        assert route["facts_readable"] is False


def test_complete_empty_window_is_not_connection_failure(store):
    account_id = seed(store, day=DAY - timedelta(days=1))
    add_window(store, account_id, complete=True)
    with store() as session:
        route = next(
            iter(DataSourceRouter(session, "default", NOW).resolve(DAY, DAY).values())
        )
        assert route["connection"] == "healthy"
        assert route["mode"] == "primary"
        assert route["sync_status"] == "succeeded"
        assert route["coverage"] == "no_data"
        assert route["window_status"] == "complete"
        assert route["facts_count"] == 0


@pytest.mark.parametrize(
    "zone,expected",
    [
        ("America/Los_Angeles", "not_started"),
        ("Europe/Kiev", "no_data"),
    ],
)
def test_selected_calendar_day_uses_account_timezone(store, zone, expected):
    seed(store, zone=zone, day=DAY - timedelta(days=1))
    with store() as session:
        route = next(
            iter(DataSourceRouter(session, "default", NOW).resolve(DAY, DAY).values())
        )
        assert route["coverage"] == expected


def test_overview_today_rolls_over_in_each_account_timezone(store):
    seed(store, zone="America/Los_Angeles", day=DAY - timedelta(days=1))
    with (
        store() as session,
        patch("services.providers.router.utc_now", return_value=NOW),
    ):
        before = dashboard_today(session, "default", now=NOW)
        after = dashboard_today(session, "default", now=NOW + timedelta(hours=8))
        assert before["groups"][0]["start"] == "2026-10-08"
        assert after["groups"] == []
        assert after["sources"][0]["coverage"] == "no_data"


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {"summary": '{"daily_used":17,"daily_limit":20000,"token":"secret"}'},
            (17, 20000),
        ),
        ({"summary": {"daily_used": 0, "daily_limit": 20000}}, (0, 20000)),
        ({"summary": "unknown"}, (None, None)),
        ({"summary": '{"daily_used":true,"daily_limit":-1}'}, (None, None)),
    ],
)
def test_quota_known_summary_only(payload: dict[str, Any], expected):
    result = quota_numbers(payload)
    assert (result["used"], result["limit"]) == expected
    assert "token" not in result
