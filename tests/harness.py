"""Utilitários dos testes ponta a ponta locais (sem Docker): servidor numa thread, cliente no processo."""
import contextlib
import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("client", "server"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

from sync_client.config import ClientConfig  # noqa: E402
from sync_client.main import run as run_client  # noqa: E402
from sync_server.config import ServerConfig  # noqa: E402
from sync_server.handler import build_server  # noqa: E402


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class LocalRun:
    """Executa uma rodada completa e deixa os arquivos em self.client_dir / self.server_dir."""

    def __init__(self, n_events=100, rate_per_s=10.0, drop_response_rate=0.0, server_seed=0, **client_kw):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.client_dir, self.server_dir = base / "client", base / "server"
        self.server_cfg = ServerConfig(host="127.0.0.1", port=0, data_dir=str(self.server_dir),
                                       drop_response_rate=drop_response_rate, server_seed=server_seed)
        self.n_events = n_events
        self.rate_per_s = rate_per_s
        self.client_kw = client_kw

    def run(self):
        httpd = build_server(self.server_cfg)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        try:
            cfg = ClientConfig(server_host="127.0.0.1", server_port=httpd.server_address[1],
                               n_events=self.n_events, rate_per_s=self.rate_per_s,
                               out_dir=str(self.client_dir), **self.client_kw)
            self.exit_code = run_client(cfg)
            self.server_hashes = httpd.app.storage.entity_hashes()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
            httpd.app.close()
        return self

    def cleanup(self):
        self.tmp.cleanup()

    def client_db(self):
        return contextlib.closing(sqlite3.connect(self.client_dir / "client.sqlite"))

    def server_db(self):
        return contextlib.closing(sqlite3.connect(self.server_dir / "server.sqlite"))
