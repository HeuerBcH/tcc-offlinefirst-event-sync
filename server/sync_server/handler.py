"""HTTP do servidor (plano, seção 5.2): POST /sync/events, GET /health, GET /state/hashes."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .fault import FaultInjector
from .logs import JsonlLog
from .processor import BatchProcessor, InvalidBatch, parse_body
from .storage import ServerStorage


class SyncApp:
    """Estado compartilhado entre as threads do servidor HTTP."""

    def __init__(self, config):
        data_dir = Path(config.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.storage = ServerStorage(data_dir / "server.sqlite")
        self.requests_log = JsonlLog(data_dir / "server_requests.jsonl")
        self.events_log = JsonlLog(data_dir / "server_events.jsonl")
        self.processor = BatchProcessor(self.storage, on_event=self.events_log.write)
        self.fault = FaultInjector(config.drop_response_rate, config.server_seed)
        # Serializa processamento e sorteio de descarte: a ordem fica determinística.
        self.lock = threading.Lock()

    def close(self):
        with self.lock:
            self.storage.close()
        self.requests_log.close()
        self.events_log.close()


class SyncRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "sync-server/1"
    # TCP_NODELAY: sem isso, Nagle + ACK atrasado do cliente somam ~40 ms (ou 1 RTT extra
    # com netem) a cada resposta. Ver DECISIONS.md, D-011.
    disable_nagle_algorithm = True

    @property
    def app(self):
        return self.server.app

    def log_message(self, format, *args):
        # Os logs estruturados ficam em server_requests.jsonl / server_events.jsonl.
        pass

    def _send_json(self, status, obj):
        body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Cabeçalhos e corpo numa única escrita (um segmento TCP para respostas pequenas).
        self._headers_buffer.append(b"\r\n" + body)
        self.flush_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/state/hashes":
            with self.app.lock:
                hashes = self.app.storage.entity_hashes()
                effects = self.app.storage.effect_counts()
            self._send_json(200, {"hashes": hashes, "effects": effects})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        received_at_ns = time.time_ns()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path != "/sync/events":
            self._send_json(404, {"error": "not found"})
            return
        try:
            client_id, events = parse_body(body)
        except InvalidBatch as exc:
            self.app.events_log.write({"type": "BAD_REQUEST", "at_ns": received_at_ns, "error": str(exc)})
            self._send_json(400, {"error": str(exc)})
            return

        try:
            with self.app.lock:
                results, last_applied = self.app.processor.process(client_id, events, received_at_ns)
                drop = self.app.fault.should_drop()
        except Exception as exc:  # erro inesperado: registra e responde 500
            self.app.events_log.write({"type": "ERROR", "at_ns": time.time_ns(), "error": repr(exc)})
            self._send_json(500, {"error": "internal"})
            return

        record = {
            "received_at_ns": received_at_ns,
            "responded_at_ns": None,
            "dropped": drop,
            "client_id": client_id,
            "batch_size": len(events),
            "last_applied_seq": last_applied,
            "events": results,
        }
        if drop:
            # S9: commit feito, resposta descartada. Sem send_response; a conexão é encerrada.
            self.close_connection = True
            self.app.requests_log.write(record)
            return

        response = {
            "results": [{"event_id": r["event_id"], "status": r["status"]} for r in results],
            "last_applied_seq": last_applied,
        }
        self._send_json(200, response)
        record["responded_at_ns"] = time.time_ns()
        self.app.requests_log.write(record)


class SyncHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, SyncRequestHandler)


def build_server(config):
    app = SyncApp(config)
    return SyncHTTPServer((config.host, config.port), app)
