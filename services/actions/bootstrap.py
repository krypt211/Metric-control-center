"""Explicit local operator provisioning; does not enable advertising actions."""

import argparse
import os

from services.storage.database import make_engine, sessions
from services.storage.models import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    engine = make_engine()
    try:
        with sessions(engine).begin() as session:
            operator_id = os.environ.get("ACTION_OPERATOR_ID", "local-operator")
            workspace = os.environ.get("WORKSPACE_ID", "default")
            user = session.get(User, operator_id)
            if user is not None:
                if user.workspace_id != workspace or user.email != args.email or user.role != "operator":
                    parser.error("Existing operator does not match; no changes made")
            else:
                session.add(User(id=operator_id, workspace_id=workspace, email=args.email, role="operator"))
        print("Local operator configured; actions remain controlled by ACTIONS_ENABLED")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
