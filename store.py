import sqlite3
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


DEFAULT_DB_PATH = Path.home() / ".time_travel_clipboard.db"


@dataclass
class ClipEntry:
    id: int
    content: str
    timestamp: str
    cwd: str
    git_branch: str
    exit_code: Optional[int]
    pinned: bool

    @property
    def short_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.astimezone().strftime("%H:%M:%S")
        except Exception:
            return self.timestamp[:8]

    @property
    def short_date(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.astimezone().strftime("%Y-%m-%d")
        except Exception:
            return self.timestamp[:10]

    @property
    def preview(self) -> str:
        line = self.content.replace("\r\n", " ").replace("\n", " ").strip()
        return line[:80] + ("…" if len(line) > 80 else "")


class ClipStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or os.environ.get("TTC_DB_PATH", DEFAULT_DB_PATH))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    cwd TEXT NOT NULL DEFAULT '',
                    git_branch TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    pinned INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_ts ON clips(timestamp DESC)"
            )

    def add(
        self,
        content: str,
        cwd: str = "",
        git_branch: str = "",
        exit_code: Optional[int] = None,
        dedupe_latest: bool = True,
    ) -> Optional[int]:
        if not content or not content.strip():
            return None

        with self._connect() as conn:
            if dedupe_latest:
                row = conn.execute(
                    "SELECT id, content FROM clips ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row and row["content"] == content:
                    return row["id"]

            ts = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                """
                INSERT INTO clips (content, timestamp, cwd, git_branch, exit_code, pinned)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (content, ts, cwd, git_branch, exit_code),
            )
            return cur.lastrowid

    def list_entries(
        self,
        query: str = "",
        pinned_only: bool = False,
        branch_filter: str = "",
        limit: int = 200,
    ) -> List[ClipEntry]:
        clauses = []
        params: list = []

        if pinned_only:
            clauses.append("pinned = 1")
        if branch_filter:
            clauses.append("git_branch = ?")
            params.append(branch_filter)
        if query:
            clauses.append("(content LIKE ? OR cwd LIKE ? OR git_branch LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT id, content, timestamp, cwd, git_branch, exit_code, pinned
            FROM clips
            {where}
            ORDER BY pinned DESC, id DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            ClipEntry(
                id=r["id"],
                content=r["content"],
                timestamp=r["timestamp"],
                cwd=r["cwd"],
                git_branch=r["git_branch"],
                exit_code=r["exit_code"],
                pinned=bool(r["pinned"]),
            )
            for r in rows
        ]

    def toggle_pin(self, clip_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE clips SET pinned = CASE WHEN pinned = 1 THEN 0 ELSE 1 END WHERE id = ?",
                (clip_id,),
            )

    def delete(self, clip_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
