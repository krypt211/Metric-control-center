"""Interactive first-admin bootstrap. Password never accepted as a CLI argument."""
import argparse
from getpass import getpass
import os
from sqlalchemy import select, text
from services.auth.sessions import new_user, valid_password
from services.storage.database import make_engine, sessions
from services.storage.models import User

def read_password():
    while True:
        password = getpass("Password (12 to 256 characters; input hidden): ")
        if not valid_password(password):
            print("Password must contain 12 to 256 characters (at most 1024 UTF-8 bytes). Please retry.")
            continue
        if password != getpass("Repeat password: "):
            print("Passwords do not match. Please retry.")
            continue
        return password

def main():
    parser = argparse.ArgumentParser()
    workspace = os.environ.get("WORKSPACE_ID", "default")
    parser.add_argument("--workspace", default=workspace)
    args = parser.parse_args()
    if args.workspace != workspace:
        raise SystemExit("Workspace must match the running backend WORKSPACE_ID")
    db = None
    try:
        db = make_engine()
        if db.dialect.name != "postgresql":
            raise ValueError("First-admin bootstrap requires the backend PostgreSQL database")
        with sessions(db)() as session:
            exists = session.scalar(select(User.id).where(
                User.workspace_id == workspace, User.role == "admin", User.password_hash.is_not(None)))
        if exists:
            raise ValueError("Admin already exists; password unchanged. Use authenticated user administration.")
        print(f"Target PostgreSQL database: {db.url.database}; workspace: {workspace}")
        login = input("Admin email/login: ").strip()
        password = read_password()
        with sessions(db).begin() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(670718401)"))
            if session.scalar(select(User.id).where(
                User.workspace_id == workspace, User.role == "admin", User.password_hash.is_not(None))):
                raise ValueError("Admin already exists; password unchanged. Use authenticated user administration.")
            new_user(session, workspace, login, password, "admin")
        print("First administrator created. No password was printed or saved in plaintext.")
        print("Local login: http://127.0.0.1:3000/login")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("ADMIN_BOOTSTRAP_CANCELLED: administrator was not created") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("ADMIN_BOOTSTRAP_FAILED: administrator was not created; check backend readiness") from None
    finally:
        if db is not None:
            db.dispose()

if __name__ == "__main__":
    main()
