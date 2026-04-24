from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Recipe:
    name: str
    description: str
    entity: str
    query: dict[str, Any]
    verified: bool


class KnowledgeStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipes (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    entity TEXT NOT NULL,
                    query_json TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipe_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_name TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS synonyms (
                    term TEXT NOT NULL,
                    canonical TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(term, canonical)
                )
                """
            )

    def save_recipe(self, recipe: Recipe) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recipes(name, description, entity, query_json, verified, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    entity=excluded.entity,
                    query_json=excluded.query_json,
                    verified=excluded.verified,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    recipe.name,
                    recipe.description,
                    recipe.entity,
                    json.dumps(recipe.query, ensure_ascii=False),
                    1 if recipe.verified else 0,
                ),
            )
        return {"ok": True, "name": recipe.name, "verified": recipe.verified}

    def list_recipes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, description, entity, query_json, verified, created_at, updated_at FROM recipes ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "name": r["name"],
                "description": r["description"],
                "entity": r["entity"],
                "query": json.loads(r["query_json"]),
                "verified": bool(r["verified"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_recipe(self, name: str) -> Recipe | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM recipes WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        return Recipe(
            name=row["name"],
            description=row["description"],
            entity=row["entity"],
            query=json.loads(row["query_json"]),
            verified=bool(row["verified"]),
        )

    def log_recipe_run(self, recipe_name: str, ok: bool, message: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recipe_runs(recipe_name, ok, message) VALUES (?, ?, ?)",
                (recipe_name, 1 if ok else 0, message),
            )
