from datetime import timedelta
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from test_sync import DAY, NOW, ROOT, StorageFixture
from workers.ingestion import app, sync_insights, window


class FrequencyWorkerTests(StorageFixture, unittest.TestCase):
    def schema_path(self, **changes):
        schema = json.loads((ROOT / "config/metricflow-frequency-schema.example.json").read_text(encoding="utf-8"))
        schema.update(changes)
        path = Path(self.directory.name) / "frequency.json"
        path.write_text(json.dumps(schema), encoding="utf-8")
        return str(path)

    def test_disabled_or_missing_schema_never_loads_credentials_or_creates_connector(self):
        with patch("workers.ingestion.SyncEngine") as engine, patch("workers.ingestion.read_key_file") as key:
            with patch.dict(os.environ, {"SYNC_ENABLED": "false"}):
                self.assertEqual(sync_insights.run("frequency")["status"], "disabled")
            with patch.dict(os.environ, {"SYNC_ENABLED": "true", "METRICFLOW_FREQUENCY_SCHEMA_FILE": ""}):
                self.assertEqual(sync_insights.run("frequency")["status"], "schema_not_configured")
            engine.assert_not_called()
            key.assert_not_called()

    def test_wrong_level_or_missing_frequency_mapping_is_rejected_before_connector(self):
        path = self.schema_path(entity_level="ad")
        with patch.dict(os.environ, {"SYNC_ENABLED": "true", "METRICFLOW_FREQUENCY_SCHEMA_FILE": path}), patch("workers.ingestion.SyncEngine") as engine:
            self.assertEqual(sync_insights.run("frequency")["status"], "frequency_schema_not_configured")
            engine.assert_not_called()
        path = self.schema_path()
        schema = json.loads(Path(path).read_text(encoding="utf-8"))
        del schema["fields"]["frequency"]
        del schema["fields"]["reach"]
        Path(path).write_text(json.dumps(schema), encoding="utf-8")
        with patch.dict(os.environ, {"SYNC_ENABLED": "true", "METRICFLOW_FREQUENCY_SCHEMA_FILE": path}), patch("workers.ingestion.SyncEngine") as engine:
            self.assertEqual(sync_insights.run("frequency")["status"], "frequency_schema_not_configured")
            engine.assert_not_called()

    def test_valid_parent_job_uses_read_key_and_shared_quota_engine(self):
        from services.providers.models import ProviderConnection
        with self.sessions.begin() as session:
            session.add(ProviderConnection(workspace_id="default",provider="metricflow",enabled=True,
                credential_source="server",revision=1,config={},status="healthy",permissions={},capabilities={},quota={},updated_at=NOW))
        path = self.schema_path()
        env = {"SYNC_ENABLED": "true", "METRICFLOW_FREQUENCY_SCHEMA_FILE": path,
               "METRICFLOW_READ_KEY_FILE": "read-key-path", "SYNC_DAILY_BUDGET": "123", "WORKSPACE_ID": "default"}
        with patch.dict(os.environ, env), patch("workers.ingestion.factory", return_value=self.sessions), patch("workers.ingestion.utc_now", return_value=NOW), patch("workers.ingestion.read_key_file", return_value="mfk_test") as key, patch("workers.ingestion.SyncEngine") as constructor:
            constructor.return_value.run = AsyncMock(return_value={"status": "succeeded"})
            self.assertEqual(sync_insights.run("frequency")["status"], "succeeded")
            key.assert_called_once_with("read-key-path")
            self.assertEqual(constructor.call_args.args[1].kind, "adset")
            self.assertEqual(constructor.call_args.kwargs["daily_budget"], 123)
            constructor.return_value.run.assert_awaited_once_with("frequency", DAY-timedelta(days=15), DAY)

    def test_daily_schedule_and_window_cover_fourteen_completed_account_days(self):
        self.assertEqual(app.conf.beat_schedule["frequency"]["args"], ["frequency"])
        with patch("workers.ingestion.utc_now", return_value=NOW):
            self.assertEqual(window("frequency"), (DAY-timedelta(days=15), DAY))
