"""`cli logs prune`: delete session logs not written to for N days. Nothing is deleted automatically."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from core.logs import session_files
from core.paths import logs_dir


def prune(root: Path, days: int, dry_run: bool) -> Dict[str, Any]:
    if days < 1:
        raise ValueError("--days 要 1 或更大。")
    cutoff = time.time() - days * 86400
    old: List[Path] = []
    kept = 0
    for _surface, path in session_files(root):
        if path.stat().st_mtime < cutoff:
            old.append(path)
        else:
            kept += 1
    freed = sum(path.stat().st_size for path in old)
    base = logs_dir(root)
    if not dry_run:
        for path in old:
            path.unlink()
            try:
                path.parent.rmdir()  # only when it is empty
            except OSError:
                pass
    return {
        "dry_run": dry_run,
        "days": days,
        "deleted" if not dry_run else "would_delete": [str(path.relative_to(base)) for path in old],
        "kept": kept,
        "bytes": freed,
    }
