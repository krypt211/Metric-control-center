"""Execute the Windows setup functions against isolated temporary files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows launcher")
class WindowsSetupTests(unittest.TestCase):
    def script(self, directory, body):
        # Both paths are filesystem paths, quoted as PowerShell literal strings.
        launcher = str(ROOT / "scripts" / "local.ps1").replace("'", "''")
        target = str(directory).replace("'", "''")
        command = f"$ErrorActionPreference='Stop'; . '{launcher}' -Library; $Root='{target}'; {body}"
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, text=True, check=True, timeout=15)

    def fixture(self, directory):
        Path(directory, ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")

    def test_setup_preserves_database_and_existing_keys_but_forces_safe_flags(self):
        with tempfile.TemporaryDirectory(prefix="mcc setup ") as directory:
            self.fixture(directory)
            Path(directory, ".env").write_text("POSTGRES_DB=keep_db\nWORKSPACE_ID=keep_space\nACTIONS_ENABLED=true\nACTIONS_ENABLED=true\nSYNC_ENABLED=false\n", encoding="utf-8")
            secrets = Path(directory, ".secrets"); secrets.mkdir()
            Path(secrets, "postgres_password").write_text("db_fixture", encoding="utf-8")
            Path(secrets, "metricflow_read_key").write_text("mfk_existing_fixture", encoding="utf-8")
            Path(secrets, "metricflow_write_key").write_text("write_fixture_untouched", encoding="utf-8")
            result = self.script(directory, "Initialize-LocalFiles; function Read-Host { throw 'Existing key must not prompt' }; Set-ReadKey")
            env = Path(directory, ".env").read_text(encoding="utf-8")
            self.assertIn("POSTGRES_DB=keep_db", env)
            self.assertIn("WORKSPACE_ID=keep_space", env)
            self.assertEqual(env.count("ACTIONS_ENABLED=false"), 1)
            for setting in ("LOCAL_READ_ONLY=true", "SYNC_ENABLED=true", "AI_ENABLED=false", "AI_AUTOPILOT_ALLOWED=false", "TELEGRAM_ENABLED=false"):
                self.assertIn(setting, env)
            self.assertEqual(Path(secrets, "postgres_password").read_text(), "db_fixture")
            self.assertEqual(Path(secrets, "metricflow_write_key").read_text(), "write_fixture_untouched")
            self.assertNotIn("mfk_existing_fixture", result.stdout+result.stderr)
            self.assertIn("configured", result.stdout)

    def test_hidden_key_input_saves_only_expected_read_file(self):
        for key in ("mfk_fixture_hidden_value", "mf_live_fixture_hidden_value"):
            with self.subTest(format=key.split("_fixture")[0]), tempfile.TemporaryDirectory(prefix="mcc setup ") as directory:
                self.fixture(directory)
                result = self.script(directory, f"Initialize-LocalFiles; function Read-Host {{ param($Prompt,[switch]$AsSecureString); ConvertTo-SecureString '{key}' -AsPlainText -Force }}; Set-ReadKey")
                self.assertEqual(Path(directory, ".secrets", "metricflow_read_key").read_text(), key)
                self.assertEqual(Path(directory, ".secrets", "metricflow_write_key").read_text(), "")
                self.assertNotIn(key, result.stdout+result.stderr)

    def test_invalid_input_is_not_saved_or_echoed(self):
        for key in ("invalid_fixture_hidden", "mf_live_fixture**", "mf_live_", "mf_live_fixture with_space"):
            with self.subTest(case=key), tempfile.TemporaryDirectory(prefix="mcc setup ") as directory:
                self.fixture(directory)
                result = self.script(directory, f"Initialize-LocalFiles; function Read-Host {{ param($Prompt,[switch]$AsSecureString); ConvertTo-SecureString '{key}' -AsPlainText -Force }}; try {{ Set-ReadKey; throw 'Expected validation failure' }} catch {{ if ($_.Exception.Message -notlike 'Invalid key format*') {{ throw }}; 'Invalid input rejected' }}")
                self.assertEqual(Path(directory, ".secrets", "metricflow_read_key").read_text(), "")
                self.assertNotIn(key, result.stdout+result.stderr)

    def test_schema_failure_is_application_result_not_docker_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.script(directory, "function fake-docker { $global:LASTEXITCODE=21; 'MCC_APPLICATION_STARTED'; 'MetricFlow READ API: OK'; 'READ schema: NOT VERIFIED'; 'Import: NOT STARTED' }; $script:Docker='fake-docker'; function Read-Http { @{status='ready'} }; $code=Compose -Application -Arguments @('run'); if ($code -ne 21) { throw 'Wrong exit code' }")
            self.assertIn('Docker: OK',result.stdout)
            self.assertIn('LOCAL APPLICATION: PASS',result.stdout)
            self.assertIn('Schema: FAILED',result.stdout)
            self.assertNotIn('Docker command failed',result.stdout)

    def test_missing_application_marker_is_infrastructure_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.script(directory, "function fake-docker { $global:LASTEXITCODE=21; 'container unavailable' }; $script:Docker='fake-docker'; try { Compose -Application -Arguments @('run'); throw 'Expected failure' } catch { if ($_.Exception.Message -notlike 'Docker execution failed*') { throw }; 'Infrastructure failure recognized' }")
            self.assertIn('Infrastructure failure recognized',result.stdout)
