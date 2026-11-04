"""生成邀请码（管理员在本地运行）。

用法：
    python scripts/create_invite.py
    python scripts/create_invite.py --uses 5 --days 30 --note "算法班同学"
"""

import argparse
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal
from app.db.init import init_db
from app.db.models import InviteCode

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_code() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"AI-{body}"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 AI Agent 邀请码")
    parser.add_argument("--uses", type=int, default=1, help="最多可用次数，默认 1")
    parser.add_argument("--days", type=int, default=30, help="有效天数，默认 30；0 表示永不过期")
    parser.add_argument("--note", default="", help="备注，例如班级/用途")
    args = parser.parse_args()

    if args.uses < 1:
        raise SystemExit("--uses 至少为 1")

    init_db()
    expires_at = None
    if args.days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.days)

    with SessionLocal() as db:
        code = make_code()
        while db.query(InviteCode).filter(InviteCode.code == code).first() is not None:
            code = make_code()
        db.add(
            InviteCode(
                code=code,
                max_uses=args.uses,
                expires_at=expires_at,
                note=args.note,
            )
        )
        db.commit()

    print(f"邀请码：{code}")
    print(f"可用次数：{args.uses}")
    print(f"有效期：{'永不过期' if expires_at is None else expires_at.isoformat()}")
    if args.note:
        print(f"备注：{args.note}")


if __name__ == "__main__":
    main()
