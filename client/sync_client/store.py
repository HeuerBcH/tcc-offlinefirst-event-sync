"""EventStore: SQLite do cliente com estado local e fila de eventos (plano, seções 4.2 e 4.3)."""
import json
import sqlite3
import threading
import time

from .state_hash import entity_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id           TEXT PRIMARY KEY,
  client_id          TEXT NOT NULL,
  seq                INTEGER NOT NULL UNIQUE,
  entity_id          TEXT NOT NULL,
  operation          TEXT NOT NULL CHECK (operation IN ('CREATE','UPDATE','DELETE')),
  payload            TEXT NOT NULL,
  payload_bytes      INTEGER NOT NULL,
  status             TEXT NOT NULL CHECK (status IN ('PENDING','IN_FLIGHT','ACKED')),
  attempts           INTEGER NOT NULL DEFAULT 0,
  created_at_ns      INTEGER NOT NULL,
  first_sent_at_ns   INTEGER,
  last_attempt_at_ns INTEGER,
  acked_at_ns        INTEGER,
  ack_result         TEXT
);
CREATE INDEX IF NOT EXISTS events_status_seq ON events (status, seq);
CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  data      TEXT NOT NULL,
  deleted   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

ACK_STATUSES = ("APPLIED", "DUPLICATE")
RETRY_STATUSES = ("REJECTED_GAP", "NOT_PROCESSED")


def dump_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class EventStore:
    """Acesso serializado por lock: gerador e sincronizador compartilham a conexão."""

    def __init__(self, path, client_id, queue_limit, clock=time.time_ns):
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.client_id = client_id
        self.queue_limit = queue_limit
        self.clock = clock
        self._lock = threading.Lock()
        # fault_hook(stage): usado só em testes para simular falha no meio da transação.
        self.fault_hook = None
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('next_seq', '1')")
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('client_id', ?)",
                              (client_id,))

    # --- gravação local -------------------------------------------------------------------

    def record(self, op):
        """Grava a operação do usuário: estado + evento + next_seq numa única transação.

        Devolve o seq atribuído, ou None se a fila estiver cheia (QUEUE_FULL), caso em que
        nada é gravado.
        """
        with self._lock:
            if self._unacked_count() >= self.queue_limit:
                return None
            payload = dump_json(op.payload)
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self._apply_entity(op.operation, op.entity_id, op.payload)
                self._hook("after_entity")
                seq = int(self.conn.execute(
                    "SELECT value FROM meta WHERE key = 'next_seq'").fetchone()[0])
                self.conn.execute(
                    "INSERT INTO events (event_id, client_id, seq, entity_id, operation, payload,"
                    " payload_bytes, status, attempts, created_at_ns)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)",
                    (op.event_id, self.client_id, seq, op.entity_id, op.operation, payload,
                     len(payload.encode("utf-8")), self.clock()),
                )
                self._hook("after_event")
                self.conn.execute("UPDATE meta SET value = ? WHERE key = 'next_seq'", (str(seq + 1),))
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            return seq

    def _hook(self, stage):
        if self.fault_hook is not None:
            self.fault_hook(stage)

    def _apply_entity(self, operation, entity_id, payload):
        row = self.conn.execute(
            "SELECT data, deleted FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if operation == "CREATE":
            if row is None:
                self.conn.execute("INSERT INTO entities (entity_id, data, deleted) VALUES (?, ?, 0)",
                                  (entity_id, dump_json(payload)))
                return
            operation = "UPDATE"
        if row is None or row[1]:
            return  # o gerador nunca produz esse caso; mesma regra do servidor
        if operation == "UPDATE":
            data = json.loads(row[0])
            data.update(payload)
            self.conn.execute("UPDATE entities SET data = ? WHERE entity_id = ?",
                              (dump_json(data), entity_id))
        else:
            self.conn.execute("UPDATE entities SET deleted = 1 WHERE entity_id = ?", (entity_id,))

    # --- fila ------------------------------------------------------------------------------

    def _unacked_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE status != 'ACKED'").fetchone()[0]

    def unacked_count(self):
        with self._lock:
            return self._unacked_count()

    def recover_in_flight(self):
        """Eventos IN_FLIGHT de uma execução interrompida voltam a PENDING."""
        with self._lock:
            return self.conn.execute(
                "UPDATE events SET status = 'PENDING' WHERE status = 'IN_FLIGHT'").rowcount

    def take_batch(self, limit):
        """Seleciona até `limit` eventos PENDING (seq crescente) e os marca IN_FLIGHT."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self.conn.execute(
                    "SELECT event_id, seq, entity_id, operation, payload, created_at_ns FROM events"
                    " WHERE status = 'PENDING' ORDER BY seq LIMIT ?", (limit,)).fetchall()
                if rows:
                    now = self.clock()
                    self.conn.executemany(
                        "UPDATE events SET status = 'IN_FLIGHT', attempts = attempts + 1,"
                        " last_attempt_at_ns = ?, first_sent_at_ns = COALESCE(first_sent_at_ns, ?)"
                        " WHERE event_id = ?", [(now, now, r[0]) for r in rows])
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
        return [{"event_id": r[0], "seq": r[1], "entity_id": r[2], "operation": r[3],
                 "payload": json.loads(r[4]), "created_at_ns": r[5]} for r in rows]

    def apply_results(self, event_ids, statuses):
        """Aplica a resposta do servidor ao lote enviado.

        APPLIED/DUPLICATE → ACKED; REJECTED_GAP/NOT_PROCESSED ou evento ausente da resposta → PENDING.
        """
        now = self.clock()
        acked, retry = [], []
        for event_id in event_ids:
            status = statuses.get(event_id)
            if status in ACK_STATUSES:
                acked.append((now, status, event_id))
            else:
                retry.append((event_id,))
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.executemany(
                    "UPDATE events SET status = 'ACKED', acked_at_ns = ?, ack_result = ?"
                    " WHERE event_id = ? AND status = 'IN_FLIGHT'", acked)
                self.conn.executemany(
                    "UPDATE events SET status = 'PENDING' WHERE event_id = ? AND status = 'IN_FLIGHT'",
                    retry)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
        return len(acked), len(retry)

    def release(self, event_ids):
        """Falha da requisição: o lote inteiro volta a PENDING."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.executemany(
                    "UPDATE events SET status = 'PENDING' WHERE event_id = ? AND status = 'IN_FLIGHT'",
                    [(e,) for e in event_ids])
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    # --- consultas ---------------------------------------------------------------------------

    def max_acked_at_ns(self):
        with self._lock:
            return self.conn.execute("SELECT MAX(acked_at_ns) FROM events").fetchone()[0]

    def last_created_at_ns(self):
        with self._lock:
            return self.conn.execute("SELECT MAX(created_at_ns) FROM events").fetchone()[0]

    def event_count(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def entity_hashes(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT entity_id, data, deleted FROM entities ORDER BY entity_id").fetchall()
        return {eid: entity_hash(eid, json.loads(data), deleted) for eid, data, deleted in rows}

    def close(self):
        with self._lock:
            self.conn.close()
