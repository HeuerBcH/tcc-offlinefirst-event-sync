"""Métricas por execução (plano, seção 7.1; Metodologia, Quadro 4).

    python analysis/metrics.py [--raw data/raw] [--out data/processed/metrics_per_run.csv]

Lê cada execução em <raw>/<run_id>/ (aquecimentos em <raw>/_warmup/ são ignorados) e grava
uma linha por execução.
"""
import argparse
import contextlib
import csv
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

NAN = float("nan")
NS = 1_000_000_000

COLUMNS = [
    "run_id", "scenario", "repetition", "converged", "n_events",
    "R1_pct", "R2", "R4", "R5_pct",
    "D1_median_ms", "D1_p95_ms", "D1_max_ms", "D2_s", "D3_s", "D3_n", "D4_events_per_s",
    "D5", "D6", "C1", "C2", "C3", "C4",
    "n_requests", "applied_ignored_conflict", "seq_anomalies", "queue_full", "wall_time_s",
]


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def query(db_path, sql):
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        return conn.execute(sql).fetchall()


def load_run(run_dir):
    run_dir = Path(run_dir)
    server_hashes = read_json(run_dir / "server_state_hashes.json", {})
    return {
        "dir": run_dir,
        "manifest": read_json(run_dir / "manifest.json"),
        "events": query(run_dir / "client" / "client.sqlite",
                        "SELECT event_id, seq, created_at_ns, acked_at_ns, attempts, payload_bytes"
                        " FROM events ORDER BY seq"),
        "applied": query(run_dir / "server" / "server.sqlite",
                         "SELECT event_id, seq, applied_at_ns, effect FROM applied_events"
                         " ORDER BY applied_at_ns, rowid"),
        "requests": read_jsonl(run_dir / "client" / "requests.jsonl"),
        "server_requests": read_jsonl(run_dir / "server" / "server_requests.jsonl"),
        "server_events": read_jsonl(run_dir / "server" / "server_events.jsonl"),
        "client_events": read_jsonl(run_dir / "client" / "client_events.jsonl"),
        "network": read_jsonl(run_dir / "network_events.jsonl"),
        "client_hashes": read_json(run_dir / "client" / "client_state_hashes.json", {}),
        "server_hashes": server_hashes.get("hashes", {}),
    }


def restorations(run):
    """Instantes de restauração da rede: 'restore' (S5/S6) e 'online' (ciclos)."""
    return [r["t_applied_ns"] for r in run["network"] if r["label"] in ("restore", "online")]


def t_ref_ns(run):
    """t_ref = max(último created_at_ns, instante de restauração quando houver: S5/S6)."""
    last_created = max(e[2] for e in run["events"])
    restore = [r["t_applied_ns"] for r in run["network"] if r["label"] == "restore"]
    return max([last_created] + restore)


def queue_series(events):
    """Varredura (instante, tamanho da fila = criados − ACKED). No empate, o ACK vem antes."""
    points = [(e[2], 1) for e in events] + [(e[3], -1) for e in events if e[3] is not None]
    points.sort(key=lambda p: (p[0], p[1]))
    size, series = 0, []
    for t, delta in points:
        size += delta
        series.append((t, size))
    return series


def queue_nonempty_at(events, t):
    return any(e[2] <= t and (e[3] is None or e[3] > t) for e in events)


def d3_values(run):
    ok_finishes = sorted(r["finished_at_ns"] for r in run["requests"] if r["outcome"] == "ok")
    values = []
    for r in restorations(run):
        if not queue_nonempty_at(run["events"], r):
            continue
        after = [f for f in ok_finishes if f >= r]
        if after:
            values.append((after[0] - r) / NS)
    return values


def c3(applied):
    seqs = [a[1] for a in applied]
    if not seqs:
        return 0
    return (1 if seqs[0] != 1 else 0) + sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1)


def c4(client_hashes, server_hashes):
    one_side = set(client_hashes) ^ set(server_hashes)
    differ = sum(1 for k in set(client_hashes) & set(server_hashes)
                 if client_hashes[k] != server_hashes[k])
    return len(one_side) + differ


def compute_run_metrics(run):
    m = run["manifest"]
    events = run["events"]
    n = len(events)
    converged = bool(m.get("converged"))
    distinct_applied = len({a[0] for a in run["applied"]})
    requests = run["requests"]

    latencies_ms = np.array([(e[3] - e[2]) / 1e6 for e in events if e[3] is not None], dtype=float)
    acked = [e[3] for e in events if e[3] is not None]
    d2 = (max(acked) - t_ref_ns(run)) / NS if converged and acked else NAN
    d3 = d3_values(run)
    payload_total = sum(e[5] for e in events)

    applied_in = defaultdict(int)
    duplicates = 0
    for req in run["server_requests"]:
        for ev in req["events"]:
            if ev["status"] == "APPLIED":
                applied_in[ev["event_id"]] += 1
            elif ev["status"] == "DUPLICATE":
                duplicates += 1

    effects = Counter(a[3] for a in run["applied"])
    return {
        "run_id": m["run_id"],
        "scenario": m["scenario"],
        "repetition": m["repetition"],
        "converged": converged,
        "n_events": n,
        "R1_pct": distinct_applied / n * 100 if n else NAN,
        "R2": n - distinct_applied,
        "R4": sum(e[4] for e in events) / n if n else NAN,
        "R5_pct": (sum(1 for r in requests if r["outcome"] != "ok") / len(requests) * 100
                   if requests else NAN),
        "D1_median_ms": float(np.median(latencies_ms)) if latencies_ms.size else NAN,
        "D1_p95_ms": (float(np.percentile(latencies_ms, 95, method="linear"))
                      if latencies_ms.size else NAN),
        "D1_max_ms": float(latencies_ms.max()) if latencies_ms.size else NAN,
        "D2_s": d2,
        "D3_s": float(np.mean(d3)) if d3 else NAN,
        "D3_n": len(d3),
        "D4_events_per_s": n / d2 if m["scenario"] == "S6" and d2 and not math.isnan(d2) else NAN,
        "D5": ((sum(r["bytes_sent"] for r in requests) + sum(r["bytes_recv"] for r in requests))
               / payload_total if payload_total else NAN),
        "D6": max((s for _, s in queue_series(events)), default=0),
        "C1": sum(1 for c in applied_in.values() if c > 1),
        "C2": duplicates,
        "C3": c3(run["applied"]),
        "C4": c4(run["client_hashes"], run["server_hashes"]),
        "n_requests": len(requests),
        "applied_ignored_conflict": effects.get("APPLIED_IGNORED_CONFLICT", 0),
        "seq_anomalies": sum(1 for e in run["server_events"] if e.get("type") == "SEQ_ANOMALY"),
        "queue_full": sum(1 for e in run["client_events"] if e.get("type") == "QUEUE_FULL"),
        "wall_time_s": m.get("wall_time_s", NAN),
    }


def find_runs(raw_dir):
    """Execuções válidas (com manifesto), sem aquecimentos."""
    runs = []
    for manifest in sorted(Path(raw_dir).glob("*/manifest.json")):
        if manifest.parent.name == "_warmup":
            continue
        m = read_json(manifest)
        if m.get("is_warmup") or m.get("converged") is None:
            continue  # aquecimento ou execução interrompida antes da coleta
        runs.append(manifest.parent)
    return runs


def write_csv(rows, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in COLUMNS})


# Métricas resumidas por cenário em summary_preliminary.csv (R3 vem de `converged`).
SUMMARY_METRICS = [c for c in COLUMNS if c not in ("run_id", "scenario", "repetition", "converged")]


def scenario_key(s):
    return (len(s), s)


def preliminary_summary(rows):
    """Por cenário e métrica: valores individuais (ordem de repetição), média, mínimo e máximo.

    Com n = 3 o desvio padrão é pouco informativo; por isso os valores individuais aparecem.
    """
    by_sc = defaultdict(list)
    for r in rows:
        by_sc[r["scenario"]].append(r)
    width = max((len(v) for v in by_sc.values()), default=0)
    out = []
    for sc in sorted(by_sc, key=scenario_key):
        sc_rows = sorted(by_sc[sc], key=lambda r: (r["repetition"] is None, r["repetition"]))
        r3 = sum(1 for r in sc_rows if not r["converged"]) / len(sc_rows) * 100
        metrics = [("R3_pct", None)] + [(m, m) for m in SUMMARY_METRICS]
        for name, col in metrics:
            vals = [r3] if col is None else [float(r[col]) for r in sc_rows]
            finite = [v for v in vals if not math.isnan(v)]
            line = {"scenario": sc, "metric": name, "n": len(finite),
                    "run_ids": ";".join(r["run_id"] for r in sc_rows) if col else ""}
            for i in range(width):
                line[f"value_{i + 1}"] = vals[i] if col is not None and i < len(vals) else ""
            if col is None:
                line["value_1"] = r3
            line["mean"] = float(np.mean(finite)) if finite else NAN
            line["min"] = min(finite) if finite else NAN
            line["max"] = max(finite) if finite else NAN
            out.append(line)
    return out


def write_rows(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", "--raw", dest="raw", default="data/raw",
                    help="diretório com as execuções (data/raw)")
    ap.add_argument("--out", default="data/processed",
                    help="diretório de saída (ou caminho de um .csv para metrics_per_run)")
    args = ap.parse_args(argv)
    runs = find_runs(args.raw)
    if not runs:
        print(f"nenhuma execução encontrada em {args.raw}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out_dir, metrics_csv = (out.parent, out) if out.suffix == ".csv" else (out, out / "metrics_per_run.csv")
    rows = [compute_run_metrics(load_run(d)) for d in runs]
    write_csv(rows, metrics_csv)
    write_rows(preliminary_summary(rows), out_dir / "summary_preliminary.csv")
    from export_raw import export_all  # importação tardia: export_raw importa este módulo
    export_all(args.raw, out_dir / "raw_csv")
    print(f"{len(rows)} execuções -> {metrics_csv}, {out_dir / 'summary_preliminary.csv'} "
          f"e dados brutos em CSV em {out_dir / 'raw_csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
