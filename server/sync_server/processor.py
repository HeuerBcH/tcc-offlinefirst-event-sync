"""Processamento de lotes: deduplicação, ordem por seq e LWW (plano, seções 5.4 e 5.5)."""
import json
import time

from .storage import dump_data

APPLIED = "APPLIED"
DUPLICATE = "DUPLICATE"
REJECTED_GAP = "REJECTED_GAP"
NOT_PROCESSED = "NOT_PROCESSED"

EFFECT_OK = "APPLIED_OK"
EFFECT_IGNORED = "APPLIED_IGNORED_CONFLICT"

OPERATIONS = ("CREATE", "UPDATE", "DELETE")


class InvalidBatch(ValueError):
    pass


def parse_body(body):
    """Decodifica e valida o corpo de POST /sync/events; devolve (client_id, events)."""
    try:
        req = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidBatch(f"JSON inválido: {exc}") from exc
    if not isinstance(req, dict):
        raise InvalidBatch("corpo não é um objeto JSON")
    client_id = req.get("client_id")
    events = req.get("events")
    if not isinstance(client_id, str) or not client_id:
        raise InvalidBatch("client_id ausente")
    if not isinstance(events, list):
        raise InvalidBatch("events não é uma lista")
    for ev in events:
        if not isinstance(ev, dict):
            raise InvalidBatch("evento não é um objeto")
        if not isinstance(ev.get("event_id"), str) or not isinstance(ev.get("entity_id"), str):
            raise InvalidBatch("event_id/entity_id inválido")
        seq = ev.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise InvalidBatch("seq inválido")
        if ev.get("operation") not in OPERATIONS:
            raise InvalidBatch("operation inválida")
        if not isinstance(ev.get("payload"), dict):
            raise InvalidBatch("payload inválido")
    return client_id, events


class BatchProcessor:
    def __init__(self, storage, clock=time.time_ns, on_event=None):
        self.storage = storage
        self.clock = clock
        # on_event(record): anomalias (SEQ_ANOMALY) para server_events.jsonl.
        self.on_event = on_event or (lambda record: None)

    def process(self, client_id, events, received_at_ns):
        """Processa um lote numa única transação; devolve (results, last_applied_seq).

        results: lista de {"event_id", "seq", "status"} em ordem crescente de seq.
        O commit acontece antes do retorno; a resposta HTTP só é enviada depois dele.
        """
        conn = self.storage.conn
        results = []
        conn.execute("BEGIN IMMEDIATE")
        try:
            last = self.storage.last_applied_seq(client_id)
            interrupted = False
            for ev in sorted(events, key=lambda e: e["seq"]):
                event_id, seq = ev["event_id"], ev["seq"]
                if interrupted:
                    status = NOT_PROCESSED
                elif self._is_applied(event_id):
                    status = DUPLICATE
                elif seq == last + 1:
                    effect = self._apply_entity(ev["operation"], ev["entity_id"], ev["payload"])
                    conn.execute(
                        "INSERT INTO applied_events (event_id, client_id, seq, received_at_ns,"
                        " applied_at_ns, effect) VALUES (?, ?, ?, ?, ?, ?)",
                        (event_id, client_id, seq, received_at_ns, self.clock(), effect),
                    )
                    last = seq
                    status = APPLIED
                elif seq > last + 1:
                    status = REJECTED_GAP
                    interrupted = True
                else:
                    # seq já aplicado com event_id desconhecido: não deveria ocorrer (defeito).
                    self.on_event({
                        "type": "SEQ_ANOMALY", "at_ns": self.clock(), "client_id": client_id,
                        "event_id": event_id, "seq": seq, "last_applied_seq": last,
                    })
                    status = REJECTED_GAP
                    interrupted = True
                results.append({"event_id": event_id, "seq": seq, "status": status})
            conn.execute(
                "INSERT INTO client_progress (client_id, last_applied_seq) VALUES (?, ?)"
                " ON CONFLICT(client_id) DO UPDATE SET last_applied_seq = excluded.last_applied_seq",
                (client_id, last),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return results, last

    def _is_applied(self, event_id):
        row = self.storage.conn.execute(
            "SELECT 1 FROM applied_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row is not None

    def _apply_entity(self, operation, entity_id, payload):
        """Regra de conflito LWW na ordem de aplicação (plano, seção 5.5)."""
        conn = self.storage.conn
        current = self.storage.entity(entity_id)
        if operation == "CREATE":
            if current is None:
                conn.execute(
                    "INSERT INTO entities (entity_id, data, deleted) VALUES (?, ?, 0)",
                    (entity_id, dump_data(payload)),
                )
                return EFFECT_OK
            # CREATE com entity_id existente: tratado como UPDATE com todos os campos.
            operation = "UPDATE"
        if current is None or current["deleted"]:
            return EFFECT_IGNORED
        if operation == "UPDATE":
            data = current["data"]
            data.update(payload)
            conn.execute(
                "UPDATE entities SET data = ? WHERE entity_id = ?", (dump_data(data), entity_id)
            )
        else:
            conn.execute("UPDATE entities SET deleted = 1 WHERE entity_id = ?", (entity_id,))
        return EFFECT_OK
