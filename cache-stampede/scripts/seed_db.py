#!/usr/bin/env python3
"""Create sample SQLite origin database."""

import argparse
import sqlite3
from pathlib import Path


def seed(db_path: Path, count: int) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute("DELETE FROM items")

        rows = [
            (item_id, f"item-{item_id}", f"payload-for-item-{item_id}")
            for item_id in range(1, count + 1)
        ]
        conn.executemany(
            "INSERT INTO items (id, name, payload) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Seeded {len(rows)} items into {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed origin SQLite database")
    parser.add_argument(
        "--db",
        default="data/app.db",
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of items to seed (ids 1..count)",
    )
    args = parser.parse_args()
    seed(Path(args.db), args.count)


if __name__ == "__main__":
    main()
