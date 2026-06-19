#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import MobileAccess
from app.services.mobile_access import create_access


def main():
    parser = argparse.ArgumentParser(description="Manage Beathill Studio friend access codes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("label")
    create.add_argument(
        "--publishing",
        action="store_true",
        help="Allow posting through the server's currently connected social accounts",
    )

    subparsers.add_parser("list")

    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("owner")

    args = parser.parse_args()
    db = SessionLocal()
    try:
        if args.command == "create":
            access, token = create_access(db, args.label, args.publishing)
            print(f"label={access.label}")
            print(f"owner={access.owner}")
            print(f"publishing_enabled={access.publishing_enabled}")
            print(f"access_code={token}")
        elif args.command == "list":
            for access in db.query(MobileAccess).order_by(MobileAccess.created_at).all():
                print(
                    f"{access.owner}\t{access.label}\tactive={access.active}"
                    f"\tpublishing={access.publishing_enabled}"
                    f"\tlast_used={access.last_used_at or '-'}"
                )
        elif args.command == "revoke":
            access = db.query(MobileAccess).filter(MobileAccess.owner == args.owner).first()
            if not access:
                raise SystemExit("Access code not found")
            access.active = False
            db.commit()
            print(f"revoked={access.owner}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
