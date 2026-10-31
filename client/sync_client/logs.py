"""Escrita de logs JSONL (uma linha por registro)."""
import json
import threading


class JsonlLog:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, record):
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            if self._fh.closed:
                return
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self):
        with self._lock:
            if not self._fh.closed:
                self._fh.close()
