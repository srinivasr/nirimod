"""Automatic config backup management."""

import re
import shutil
from datetime import datetime
from pathlib import Path

from nirimod import kdl_parser


def backup_all_sources(source_files: set[Path], limit: int = 10) -> Path | None:
    if not source_files:
        return None

    kdl_parser.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    existing_gens = []
    for p in kdl_parser.BACKUP_DIR.iterdir():
        if p.is_dir():
            m = re.match(r"^(?:\(Gen|v|gen)(\d+)", p.name, re.IGNORECASE)
            if m:
                existing_gens.append(int(m.group(1)))
    next_gen = max(existing_gens) + 1 if existing_gens else 1

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    dest_dir = kdl_parser.BACKUP_DIR / f"(Gen{next_gen}){ts}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src in sorted(source_files):
        if not src.exists():
            continue
        try:
            rel = src.relative_to(kdl_parser.NIRI_CONFIG.parent)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except ValueError:
            shutil.copy2(src, dest_dir / src.name)

    if limit > 0:
        backups = sorted(
            [
                p
                for p in kdl_parser.BACKUP_DIR.iterdir()
                if p.is_dir()
                and re.match(r"^(?:\(Gen|v|gen)\d+", p.name, re.IGNORECASE)
            ],
            key=lambda p: p.stat().st_mtime,
        )
        while len(backups) > limit:
            oldest = backups.pop(0)
            shutil.rmtree(oldest)

    return dest_dir
