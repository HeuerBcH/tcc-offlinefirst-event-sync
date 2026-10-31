"""Ponto de entrada de uma execução do cliente: python -m sync_client.main [opções]

Termina sozinho (código 0) quando as N operações foram geradas e todos os eventos estão ACKED,
gravando client_done.json. Com SIGTERM (limite de tempo do orquestrador) encerra com código 3
sem client_done.json; os dados já gravados ficam no SQLite.
"""
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from .config import ClientConfig
from .generator import generate_operations, operation_counts, run_generation
from .logs import JsonlLog
from .store import EventStore
from .synchronizer import Synchronizer, start_thread
from .transport import Transport


def write_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def run(config, stop_event=None):
    out = Path(config.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stop = stop_event or threading.Event()
    (out / "client.pid").write_text(str(os.getpid()), encoding="utf-8")

    mix = (config.mix_create, config.mix_update, config.mix_delete)
    ops = generate_operations(config.n_events, config.seed, mix, config.text_field_len)
    write_json(out / "client_info.json", {
        "config": config.to_dict(),
        "operation_counts": operation_counts(ops),
        "python_version": sys.version,
    })

    store = EventStore(out / "client.sqlite", config.client_id, config.queue_limit)
    store.recover_in_flight()
    requests_log = JsonlLog(out / "requests.jsonl")
    events_log = JsonlLog(out / "client_events.jsonl")
    wake, generation_done = threading.Event(), threading.Event()
    sync = Synchronizer(config, store, Transport(config.server_host, config.server_port,
                                                 config.request_timeout_s),
                        requests_log, events_log, wake, generation_done, stop)
    thread = start_thread(sync)

    # t0 compartilhado com o orquestrador: instante absoluto no relógio do kernel.
    wait_s = max(0.0, (config.start_at_ns - time.time_ns()) / 1e9) if config.start_at_ns else 0.0
    start_mono = time.monotonic() + wait_s
    t0_ns = time.time_ns() + int(wait_s * 1e9)
    queue_full = []
    processed = 0

    def on_queue_full(op):
        queue_full.append(op.index)
        events_log.write({"type": "QUEUE_FULL", "at_ns": time.time_ns(), "index": op.index,
                          "event_id": op.event_id})

    try:
        processed = run_generation(ops, store, 1.0 / config.rate_per_s, start_mono,
                                   on_recorded=lambda op: wake.set(),
                                   on_queue_full=on_queue_full, stop_event=stop)
        write_json(out / "generation_done.json", {
            "t0_ns": t0_ns,
            "processed": processed,
            "recorded": store.event_count(),
            "queue_full": len(queue_full),
            "last_created_at_ns": store.last_created_at_ns(),
            "completed": processed == len(ops),
        })
        generation_done.set()
        wake.set()
        while thread.is_alive():
            thread.join(0.5)
    except Exception as exc:
        events_log.write({"type": "ERROR", "at_ns": time.time_ns(), "where": "main",
                          "error": repr(exc)})
        stop.set()
        thread.join(5)
        raise
    finally:
        write_json(out / "client_state_hashes.json", store.entity_hashes())
        converged = sync.converged and processed == len(ops)
        if converged:
            write_json(out / "client_done.json", {
                "t0_ns": t0_ns,
                "t_queue_empty_ns": store.max_acked_at_ns(),
                "finished_at_ns": time.time_ns(),
                "requests": sync.request_id,
            })
        requests_log.close()
        events_log.close()
        store.close()
    return 0 if converged else 3


def main(argv=None):
    config = ClientConfig.from_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: stop.set())
    signal.signal(signal.SIGINT, lambda signum, frame: stop.set())
    return run(config, stop)


if __name__ == "__main__":
    sys.exit(main())
