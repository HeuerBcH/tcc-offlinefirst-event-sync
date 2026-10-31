"""Exporta os dados brutos de cada execução para CSV (Artefato 7). Não altera data/raw.

    python analysis/export_raw.py [--in data/raw] [--out data/processed/raw_csv]

Também é chamado por metrics.py. Para cada execução válida gera, em <out>/<run_id>/:
  events.csv            client.sqlite/events: um evento por linha, com criação, envio, ACK e tentativas
  applied_events.csv    server.sqlite/applied_events
  requests.csv          client/requests.jsonl: uma requisição por linha
  server_requests.csv   server/server_requests.jsonl: um evento por linha, com a requisição de origem
  network_events.csv    network_events.jsonl: um comando tc por linha (e o marcador t0)
Os arquivos JSONL originais já são JSON e continuam em data/raw.
"""
import argparse
import contextlib
import csv
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import find_runs, read_jsonl  # noqa: E402

EVENT_COLUMNS = ["event_id", "client_id", "seq", "entity_id", "operation", "payload", "payload_bytes",
                 "status", "attempts", "created_at_ns", "first_sent_at_ns", "last_attempt_at_ns",
                 "acked_at_ns", "ack_result"]
APPLIED_COLUMNS = ["event_id", "client_id", "seq", "received_at_ns", "applied_at_ns", "effect"]


def table_rows(db_path, table, columns):
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        return conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid").fetchall()


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def export_run(run_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    write(out_dir / "events.csv", EVENT_COLUMNS,
          table_rows(run_dir / "client" / "client.sqlite", "events", EVENT_COLUMNS))
    write(out_dir / "applied_events.csv", APPLIED_COLUMNS,
          table_rows(run_dir / "server" / "server.sqlite", "applied_events", APPLIED_COLUMNS))

    reqs = read_jsonl(run_dir / "client" / "requests.jsonl")
    cols = ["request_id", "sent_at_ns", "finished_at_ns", "batch_size", "seq_min", "seq_max", "outcome",
            "http_status", "bytes_sent", "bytes_recv", "consecutive_failures_before", "error"]
    write(out_dir / "requests.csv", cols + ["status_counts"],
          [[r.get(c) for c in cols] + [json.dumps(r.get("status_counts", {}), sort_keys=True)] for r in reqs])

    rows = []
    for i, r in enumerate(read_jsonl(run_dir / "server" / "server_requests.jsonl"), start=1):
        for e in r["events"]:
            rows.append([i, r["received_at_ns"], r["responded_at_ns"], r["dropped"], r["batch_size"],
                         e["event_id"], e["seq"], e["status"]])
    write(out_dir / "server_requests.csv",
          ["server_request_index", "received_at_ns", "responded_at_ns", "dropped", "batch_size",
           "event_id", "seq", "status"], rows)

    rows = []
    for r in read_jsonl(run_dir / "network_events.jsonl"):
        if not r.get("commands"):
            rows.append([r["label"], r["spec"], "", "", r["t_first_before_ns"], r["t_applied_ns"], "", r["t_applied_ns"]])
        for c in r.get("commands", []):
            rows.append([r["label"], r["spec"], c["container"], c["command"], c["t_before_ns"],
                         c["t_after_ns"], c["returncode"], r["t_applied_ns"]])
    write(out_dir / "network_events.csv",
          ["label", "spec", "container", "command", "t_before_ns", "t_after_ns", "returncode",
           "t_applied_ns"], rows)


def export_all(raw_dir, out_dir):
    runs = find_runs(raw_dir)
    for d in runs:
        export_run(d, Path(out_dir) / d.name)
    return len(runs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="raw", default="data/raw")
    ap.add_argument("--out", default="data/processed/raw_csv")
    args = ap.parse_args(argv)
    n = export_all(args.raw, args.out)
    print(f"{n} execuções exportadas para CSV em {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
