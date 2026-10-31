"""Laço de sincronização: lotes, uma requisição por vez, backoff exponencial com full jitter
(plano, seção 4.6)."""
import threading
import time
from random import Random

SYNC_PATH = "/sync/events"


def backoff_ceiling(k, base_s, max_s):
    """Teto da k-ésima espera consecutiva (k >= 1): min(T_max, T_base × 2^(k−1))."""
    return min(max_s, base_s * (2 ** (k - 1)))


def backoff_delay(rng, k, base_s, max_s):
    """Full jitter: uniforme em [0, teto]."""
    return rng.uniform(0, backoff_ceiling(k, base_s, max_s))


class Synchronizer:
    def __init__(self, config, store, transport, requests_log, events_log,
                 wake_event, generation_done, stop_event, clock=time.time_ns):
        self.config = config
        self.store = store
        self.transport = transport
        self.requests_log = requests_log
        self.events_log = events_log
        self.wake = wake_event
        self.generation_done = generation_done
        self.stop = stop_event
        self.clock = clock
        self.rng = Random(config.jitter_seed)
        self.consecutive_failures = 0
        self.request_id = 0
        self.converged = False

    def run(self):
        try:
            self._loop()
        except Exception as exc:  # erro inesperado: registra e encerra o laço
            self.events_log.write({"type": "ERROR", "at_ns": self.clock(), "where": "synchronizer",
                                   "error": repr(exc)})
            raise
        finally:
            self.transport.close()

    def _loop(self):
        cfg = self.config
        while not self.stop.is_set():
            self.wake.clear()
            batch = self.store.take_batch(cfg.batch_size)
            if not batch:
                if self.generation_done.is_set() and self.store.unacked_count() == 0:
                    self.converged = True
                    return
                self.wake.wait(cfg.idle_check_s)
                continue
            if self._send(batch):
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
                delay = backoff_delay(self.rng, self.consecutive_failures,
                                      cfg.backoff_base_s, cfg.backoff_max_s)
                self.stop.wait(delay)

    def _send(self, batch):
        self.request_id += 1
        event_ids = [e["event_id"] for e in batch]
        body = {"client_id": self.config.client_id, "events": batch}
        sent_at = self.clock()
        result = self.transport.post_json(SYNC_PATH, body)
        finished_at = self.clock()
        status_counts = {}
        if result.outcome == "ok":
            statuses = {}
            for r in result.body["results"]:
                if isinstance(r, dict) and "event_id" in r:
                    statuses[r["event_id"]] = r.get("status")
            for event_id in event_ids:
                s = statuses.get(event_id, "MISSING")
                status_counts[s] = status_counts.get(s, 0) + 1
            self.store.apply_results(event_ids, statuses)
        else:
            self.store.release(event_ids)
        self.requests_log.write({
            "request_id": self.request_id,
            "sent_at_ns": sent_at,
            "finished_at_ns": finished_at,
            "batch_size": len(batch),
            "seq_min": batch[0]["seq"],
            "seq_max": batch[-1]["seq"],
            "outcome": result.outcome,
            "http_status": result.http_status,
            "bytes_sent": result.bytes_sent,
            "bytes_recv": result.bytes_recv,
            "status_counts": status_counts,
            "consecutive_failures_before": self.consecutive_failures,
            "error": result.error,
        })
        return result.outcome == "ok"


def start_thread(sync):
    thread = threading.Thread(target=sync.run, name="synchronizer", daemon=True)
    thread.start()
    return thread
