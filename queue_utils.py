import os
import fcntl
from pathlib import Path


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def enqueue_entry(queue_file: Path, entry: str) -> None:
    """Append a new entry to the queue file with an exclusive lock."""
    queue_file = Path(queue_file)
    _ensure_parent(queue_file)
    with open(queue_file, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.write(entry.strip() + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def dequeue_entry(queue_file: Path) -> str | None:
    """
    Pop the first entry from the queue file.
    Returns None when the queue is empty.
    """
    queue_file = Path(queue_file)
    _ensure_parent(queue_file)

    with open(queue_file, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        lines = [line.strip() for line in fh.readlines() if line.strip()]
        if not lines:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return None

        entry = lines.pop(0)
        fh.seek(0)
        fh.truncate()
        if lines:
            fh.write("\n".join(lines) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    return entry
