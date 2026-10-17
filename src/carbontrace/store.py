"""Small local SQLite evidence store; no prompts, credentials, or telemetry uploads."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from carbontrace.domain import Comparison


@dataclass(frozen=True)
class EvidenceStore:
    """Persist complete offline comparisons with bounded history queries."""

    path: Path

    def initialize(self) -> None:
        """Create the local database and table on first application startup."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS comparisons "
                "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save(self, result: Comparison) -> None:
        """Insert one complete exportable result using bound parameters."""
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute(
                "INSERT INTO comparisons (id, created_at, payload) VALUES (?, ?, ?)",
                (result.id, result.created_at, result.model_dump_json()),
            )

    def recent(self) -> list[Comparison]:
        """Return the latest twenty comparisons, newest first."""
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT payload FROM comparisons ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        return [Comparison.model_validate_json(row[0]) for row in rows]

    def get(self, run_id: str) -> Comparison | None:
        """Retrieve one comparison without interpreting its ID as SQL."""
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT payload FROM comparisons WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else Comparison.model_validate_json(row[0])
