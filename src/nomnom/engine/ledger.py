import sqlite3
from pathlib import Path

class Ledger:
    def __init__(self, state: Path):
        state.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(state / "ledger.sqlite3"))
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS contents (
                digest TEXT PRIMARY KEY, size INTEGER NOT NULL,
                destination TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS occurrences (
                card_id TEXT NOT NULL, source_path TEXT NOT NULL,
                digest TEXT NOT NULL REFERENCES contents(digest),
                size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                PRIMARY KEY(card_id, source_path, digest));
        ''')

    def destination(self, digest):
        row = self.connection.execute("SELECT destination FROM contents WHERE digest=?", (digest,)).fetchone()
        return Path(row[0]) if row else None

    def record(self, card, source, digest, size, mtime, destination):
        with self.connection:
            self.connection.execute("INSERT INTO contents VALUES (?, ?, ?) ON CONFLICT(digest) DO UPDATE SET destination=excluded.destination", (digest, size, str(destination)))
            self.connection.execute("INSERT OR REPLACE INTO occurrences VALUES (?, ?, ?, ?, ?)", (card.identity, source.relative_to(card.root).as_posix(), digest, size, mtime))

    def close(self):
        self.connection.close()
