"""Generate local secrets without displaying or overwriting them."""

from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
directory = root / ".secrets"
directory.mkdir(exist_ok=True)
for name in ("postgres_password", "action_api_token"):
    path = directory / name
    if not path.exists():
        with path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(32))
for name in ("metricflow_read_key", "metricflow_write_key", "openai_api_key", "telegram_bot_token"):
    path = directory / name
    if not path.exists():
        path.touch(exist_ok=False)
if not (root / ".env").exists():
    with (root / ".env").open("x", encoding="utf-8") as file:
        file.write((root / ".env.example").read_text(encoding="utf-8"))
print("Local configuration created. Existing files kept. For Windows READ-only setup, run setup.bat; it configures only the READ key and disables actions/AI/Telegram.")
