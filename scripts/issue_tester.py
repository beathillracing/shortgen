#!/usr/bin/env python3
"""Mint a tester (friend-role) account for the web client.

The plaintext token is shown ONCE - only its SHA-256 hash is stored, so it
cannot be recovered later. Re-run to issue a new one.

Usage:
    venv/bin/python scripts/issue_tester.py "Matti (iPhone)" --publishing
    venv/bin/python scripts/issue_tester.py --list
    venv/bin/python scripts/issue_tester.py --revoke friend-1013877a91d2693c
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import MobileAccess
from app.services.mobile_access import create_access


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?", help="Human label, e.g. 'Matti (iPhone)'")
    ap.add_argument("--publishing", action="store_true",
                    help="Allow publishing to the tester's OWN linked accounts")
    ap.add_argument("--list", action="store_true", help="List tester accounts")
    ap.add_argument("--revoke", metavar="OWNER", help="Deactivate an account by owner id")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            rows = db.query(MobileAccess).filter(MobileAccess.role == "friend").all()
            if not rows:
                print("no tester accounts")
            for a in rows:
                state = "active" if a.active else "REVOKED"
                print(f"{a.owner}  {state:8}  publishing={a.publishing_enabled}  {a.label!r}")
            return 0

        if args.revoke:
            a = db.query(MobileAccess).filter(MobileAccess.owner == args.revoke).first()
            if not a:
                print(f"no account with owner {args.revoke}", file=sys.stderr)
                return 1
            a.active = False
            db.commit()
            print(f"revoked {a.owner} ({a.label})")
            return 0

        if not args.label:
            ap.error("label is required (or use --list / --revoke)")

        access, token = create_access(db, args.label, publishing_enabled=args.publishing)
        print("Tester account created")
        print(f"  label      : {access.label}")
        print(f"  owner      : {access.owner}")
        print(f"  publishing : {access.publishing_enabled}")
        print()
        print("  TOKEN (shown once - copy it now):")
        print(f"  {token}")
        print()
        print("  Sign-in link:")
        print(f"  https://studio.beathillracing.fi/#token={token}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
