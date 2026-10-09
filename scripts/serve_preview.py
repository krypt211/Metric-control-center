"""Local empty SQLite preview; production Compose uses PostgreSQL."""

import argparse
import os
from pathlib import Path
import secrets

from alembic import command
from alembic.config import Config
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--operator", action="store_true", help="Enable local rule editor; provider actions stay disabled")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = root / ".tools"
    directory.mkdir(exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{directory / 'preview.db'}"
    os.environ["ACTIONS_ENABLED"] = "false"
    os.environ["SYNC_ENABLED"] = "false"
    os.environ["AI_ENABLED"] = "false"
    os.environ["AI_AUTOPILOT_ALLOWED"] = "false"
    os.environ["TELEGRAM_ENABLED"] = "false"
    os.environ.pop("ACTION_API_TOKEN_FILE", None)
    command.upgrade(Config(str(root / "alembic.ini")), "head")
    if args.operator:
        from services.storage.database import make_engine, sessions
        from services.storage.models import User
        token_file = directory / "preview_operator_token"
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.environ["ACTION_API_TOKEN_FILE"] = str(token_file)
        os.environ["ACTION_OPERATOR_ID"] = "preview-operator"
        engine = make_engine()
        try:
            with sessions(engine).begin() as session:
                if not session.get(User, "preview-operator"):
                    session.add(User(id="preview-operator", workspace_id=os.environ.get("WORKSPACE_ID", "default"),
                        email="preview@localhost.invalid", role="operator"))
        finally:
            engine.dispose()
        print("Local rule editor enabled; configure Next.js ACTION_API_TOKEN_FILE=.tools/preview_operator_token (absolute path).")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
