"""SQLite do servidor (plano, seção 5.3)."""
import json
import sqlite3

from .state_hash import entity_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS applied_events (
  event_id       TEXT PRIMARY KEY,
  client_id      TEXT NOT NULL,
  seq            INTEGER NOT NULL,
  received_at_ns INTEGER NOT NULL,
  applied_at_ns  INTEGER NOT NULL,
  effect         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_progress (
  client_id        TEXT PRIMARY KEY,
  last_applied_seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  data      TEXT NOT NULL,
  deleted   INTEGER NOT NULL DEFAULT 0
);
"""


def dump_data(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


class ServerStorage:
    def __init__(self, path):
        # isolation_level=None: as transações são explícitas (BEGIN/COMMIT) no processador.
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def last_applied_seq(self, client_id):
        row = self.conn.execute(
            "SELECT last_applied_seq FROM client_progress WHERE client_id = ?", (client_id,)
        ).fetchone()
        return row[0] if row else 0

    def entity(self, entity_id):
        row = self.conn.execute(
            "SELECT data, deleted FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return {"data": json.loads(row[0]), "deleted": row[1]}

    def entity_hashes(self):
        rows = self.conn.execute("SELECT entity_id, data, deleted FROM entities ORDER BY entity_id")
        return {eid: entity_hash(eid, json.loads(data), deleted) for eid, data, deleted in rows}

    def effect_counts(self):
        rows = self.conn.execute("SELECT effect, COUNT(*) FROM applied_events GROUP BY effect")
        return dict(rows.fetchall())

    def close(self):
        self.conn.close()
