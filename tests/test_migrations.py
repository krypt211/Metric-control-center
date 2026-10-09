from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from services.storage.database import make_engine
from services.storage.models import Base

ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def test_existing_ai_decision_and_linked_action_are_preserved(self):
        from services.storage.models import AIDecision, AIAction
        from test_sync import NOW
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'ai-history.db'}"
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                config = Config(str(ROOT / "alembic.ini"))
                command.upgrade(config, "0003_recommendations")
                engine = make_engine(url)
                try:
                    with engine.begin() as connection:
                        connection.execute(AIDecision.__table__.insert().values(id="decision", workspace_id="default", status="historical", created_at=NOW, payload={"reason": "existing"}))
                        connection.execute(AIAction.__table__.insert().values(id="proposal", workspace_id="default", decision_id="decision", status="historical", created_at=NOW, payload={}))
                    command.upgrade(config, "head")
                    with engine.connect() as connection:
                        self.assertEqual(connection.scalar(select(AIAction.decision_id)), "decision")
                        self.assertEqual(connection.scalar(select(AIDecision.payload)), {"reason": "existing"})
                        self.assertIsNone(connection.scalar(select(AIDecision.expires_at)))
                finally:
                    engine.dispose()

    def test_daily_history_is_preserved_when_optional_frequency_columns_are_added(self):
        from migrations.schema_v1 import AdAccount as OldAccount, Entity as OldEntity, DailyMetric as OldMetric
        from services.storage.models import DailyMetric
        from test_sync import NOW, DAY
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'daily.db'}"
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                config = Config(str(ROOT / "alembic.ini"))
                command.upgrade(config, "0002_automation")
                engine = make_engine(url)
                try:
                    with engine.begin() as connection:
                        connection.execute(OldAccount.__table__.insert().values(id="a", workspace_id="default", provider="metricflow", external_id="act_1", currency="USD", timezone="UTC", observed_at=NOW))
                        connection.execute(OldEntity.__table__.insert().values(id="e", account_id="a", kind="ad", external_id="1"))
                        connection.execute(OldMetric.__table__.insert().values(entity_id="e", day=DAY, source="metricflow", currency="USD", timezone="UTC", spend=50, observed_at=NOW, raw={}))
                    command.upgrade(config, "head")
                    with engine.connect() as connection:
                        row = connection.execute(select(DailyMetric.spend, DailyMetric.reach, DailyMetric.frequency)).one()
                        self.assertEqual(row.spend, 50)
                        self.assertIsNone(row.reach)
                        self.assertIsNone(row.frequency)
                finally:
                    engine.dispose()
    def test_existing_action_is_preserved_when_upgrading_from_v1(self):
        from migrations.schema_v1 import ActionRequest as OldRequest, AdAccount as OldAccount, Entity as OldEntity, User as OldUser
        from services.storage.models import ActionRequest
        from test_sync import NOW
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'existing.db'}"
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                config = Config(str(ROOT / "alembic.ini"))
                command.upgrade(config, "0001")
                engine = make_engine(url)
                try:
                    with engine.begin() as connection:
                        connection.execute(OldUser.__table__.insert().values(id="u", workspace_id="default", email="u@example.invalid"))
                        connection.execute(OldAccount.__table__.insert().values(id="a", workspace_id="default", provider="metricflow", external_id="act_1", currency="USD", timezone="UTC", observed_at=NOW))
                        connection.execute(OldEntity.__table__.insert().values(id="e", account_id="a", kind="adset", external_id="1"))
                        connection.execute(OldRequest.__table__.insert().values(id="r", workspace_id="default", entity_id="e", initiator_id="u", idempotency_key="one", action="pause", status="queued", created_at=NOW))
                    command.upgrade(config, "head")
                    with engine.connect() as connection:
                        self.assertEqual(connection.scalar(select(ActionRequest.provenance).where(ActionRequest.id == "r")), {})
                        self.assertEqual(connection.scalar(select(ActionRequest.status).where(ActionRequest.id == "r")), "queued")
                finally:
                    engine.dispose()
    def test_upgrade_is_repeatable_and_matches_application_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'migrated.db'}"
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                config = Config(str(ROOT / "alembic.ini"))
                command.upgrade(config, "head")
                command.upgrade(config, "head")
                engine = make_engine(url)
                try:
                    inspector = inspect(engine)
                    self.assertEqual(set(inspector.get_table_names()), set(Base.metadata.tables) | {"alembic_version"})
                    for name, table in Base.metadata.tables.items():
                        self.assertEqual({column["name"] for column in inspector.get_columns(name)}, set(table.columns.keys()))
                finally:
                    engine.dispose()

    def test_postgresql_migration_compiles_jsonb_and_unique_pending_action_index(self):
        output = StringIO()
        config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg://local:unused@localhost/local"}):
            command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        self.assertIn("JSONB", sql)
        self.assertIn("CREATE UNIQUE INDEX uq_pending_action_entity", sql)
        self.assertIn("NUMERIC(24, 8)", sql)
