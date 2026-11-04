"""批量导入课程课件。

用法（在 ai-agent 目录下）：
    python scripts/ingest_course.py --chapters ch01,ch02,ch03
    python scripts/ingest_course.py --all
"""

import argparse
import sys
from pathlib import Path

# 允许从项目根目录运行 `python scripts/ingest_course.py`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.init import init_db  # noqa: E402
from app.db.models import Document, User  # noqa: E402
from app.rag.ingest import ingest_path  # noqa: E402

DEFAULT_ROOT = DATA_DIR / "course_materials" / "算法设计与分析"
DEFAULT_COURSE = "算法设计与分析"


def _demo_user_id() -> int:
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "demo"))
    if user_id is None:
        raise SystemExit("找不到 demo 用户，先启动一次服务让 init_db() 建用户")
    return user_id


def _collect(root: Path, chapters: set[str]) -> list[Path]:
    """同一讲同时有 PPTX/PDF 时，只保留 PPTX。"""
    chosen: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".pptx", ".pdf"}:
            continue
        if chapters and path.parent.name.lower() not in chapters:
            continue
        key = str(path.with_suffix("")).lower()
        current = chosen.get(key)
        if current is None or path.suffix.lower() == ".pptx":
            chosen[key] = path
    return sorted(chosen.values(), key=lambda p: (p.parent.name.lower(), p.name))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--course", default=DEFAULT_COURSE)
    parser.add_argument("--chapters", default="", help="逗号分隔，如 ch01,ch02,ch03")
    parser.add_argument("--all", action="store_true", help="导入全部章节")
    parser.add_argument("--limit", type=int, default=0, help="只导入前 N 个文件，调试用")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.root.exists():
        raise SystemExit(f"目录不存在：{args.root}")

    init_db()

    chapters = set()
    if not args.all:
        chapters = {c.strip().lower() for c in args.chapters.split(",") if c.strip()}
        if not chapters:
            raise SystemExit("请指定 --chapters ch01,ch02,ch03 或 --all")

    files = _collect(args.root, chapters)
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit("没有找到匹配的课件")

    user_id = _demo_user_id()
    print(f"待导入 {len(files)} 个文件，用户 #{user_id}，课程「{args.course}」")
    if args.dry_run:
        for path in files:
            print("DRY", path.relative_to(args.root))
        return

    done = skipped = failed = 0
    report: list[str] = []
    for index, path in enumerate(files, start=1):
        chapter = path.parent.name
        with SessionLocal() as db:
            exists = db.scalar(
                select(Document.id).where(
                    Document.user_id == user_id,
                    Document.filename == path.name,
                    Document.course == args.course,
                )
            )
        if exists:
            skipped += 1
            report.append(f"SKIP {path.relative_to(args.root)}")
            continue

        try:
            document, chunk_count = ingest_path(
                user_id=user_id,
                path=path,
                course=args.course,
                chapter=chapter,
                original_filename=path.name,
            )
            done += 1
            line = f"OK   {path.relative_to(args.root)} -> #{document.id}, {chunk_count} chunks"
        except Exception as exc:  # noqa: BLE001
            failed += 1
            line = f"FAIL {path.relative_to(args.root)}: {type(exc).__name__}: {exc}"
        print(f"[{index}/{len(files)}] {line}")
        report.append(line)

    summary = f"\n完成：导入 {done}，跳过 {skipped}，失败 {failed}，共 {len(files)}"
    print(summary)
    report.append(summary)
    (DATA_DIR / "ingest_report.txt").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
