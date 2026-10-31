"""Estatística por cenário e comparação com S0 (plano, seção 7.2).

    python analysis/stats.py [--metrics data/processed/metrics_per_run.csv] [--out data/processed]

Saídas: summary_by_scenario.csv, comparisons_vs_S0.csv, alerts.txt e stats_info.json.
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

BASELINE = "S0"
# Métricas testadas contra S0 (Mann–Whitney bilateral + Holm). D4 só existe em S6 e D3 não
# existe em S0, então não entram em nenhuma comparação (são descritas, não testadas).
TESTED = ["R4", "R5_pct", "D1_median_ms", "D1_p95_ms", "D1_max_ms", "D2_s", "D3_s", "D5", "D6"]
DESCRIBED = TESTED + ["R1_pct", "R2", "D3_n", "D4_events_per_s", "C1", "C2", "C3", "C4",
                      "n_requests", "wall_time_s"]
# Verificadas, não testadas: valor esperado fixo (plano, seção 7.2).
EXPECTED = {"R1_pct": 100.0, "R2": 0, "C1": 0, "C3": 0, "C4": 0}
# Verificações adicionais do protótipo (esperado zero em todas as execuções).
EXPECTED_ZERO_EXTRA = ["applied_ignored_conflict", "seq_anomalies", "queue_full"]


def holm(pvalues):
    """Correção de Holm–Bonferroni; devolve os p-valores ajustados na ordem de entrada."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def to_float(value):
    if value in ("", None):
        return math.nan
    if value in ("True", "False"):
        return 1.0 if value == "True" else 0.0
    return float(value)


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def values(rows, scenario, metric):
    out = [to_float(r[metric]) for r in rows if r["scenario"] == scenario]
    return [v for v in out if not math.isnan(v)]


def scenario_order(rows):
    return sorted({r["scenario"] for r in rows}, key=lambda s: (len(s), s))


def summarize(rows):
    out = []
    for sc in scenario_order(rows):
        sc_rows = [r for r in rows if r["scenario"] == sc]
        line = {"scenario": sc, "n_runs": len(sc_rows),
                "R3_pct": sum(1 for r in sc_rows if r["converged"] != "True") / len(sc_rows) * 100}
        for metric in DESCRIBED:
            v = values(rows, sc, metric)
            line[f"{metric}_mean"] = float(np.mean(v)) if v else math.nan
            line[f"{metric}_sd"] = float(np.std(v, ddof=1)) if len(v) > 1 else math.nan
            line[f"{metric}_median"] = float(np.median(v)) if v else math.nan
        out.append(line)
    return out


def compare(rows):
    comparisons = []
    for sc in scenario_order(rows):
        if sc == BASELINE:
            continue
        for metric in TESTED:
            a, b = values(rows, sc, metric), values(rows, BASELINE, metric)
            if not a or not b:
                continue
            if len(set(a) | set(b)) == 1:
                # Todos os valores iguais nos dois grupos: sem diferença; o teste é indefinido.
                stat, p, note = math.nan, 1.0, "valores idênticos nos dois grupos; p = 1"
            else:
                res = mannwhitneyu(a, b, alternative="two-sided")
                stat, p, note = float(res.statistic), float(res.pvalue), ""
            comparisons.append({
                "scenario": sc, "metric": metric, "n_scenario": len(a), "n_baseline": len(b),
                "median_scenario": float(np.median(a)), "median_baseline": float(np.median(b)),
                "median_diff": float(np.median(a) - np.median(b)),
                "U": stat, "p": p, "note": note,
            })
    adjusted = holm([c["p"] for c in comparisons])
    for c, p_adj in zip(comparisons, adjusted):
        c["p_holm"] = p_adj
        c["significant_0_05"] = p_adj < 0.05
    return comparisons


def alerts(rows):
    out = []
    for r in rows:
        for metric, expected in EXPECTED.items():
            v = to_float(r[metric])
            if math.isnan(v) or v != expected:
                out.append(f"{r['run_id']}: {metric} = {r[metric]} (esperado {expected})")
        for metric in EXPECTED_ZERO_EXTRA:
            if to_float(r[metric]) != 0:
                out.append(f"{r['run_id']}: {metric} = {r[metric]} (esperado 0)")
        if r["converged"] != "True":
            out.append(f"{r['run_id']}: não convergiu no limite de 15 min")
    return out


def write_csv(path, rows):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metrics", default="data/processed/metrics_per_run.csv")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.metrics)

    write_csv(out / "summary_by_scenario.csv", summarize(rows))
    comparisons = compare(rows) if any(r["scenario"] == BASELINE for r in rows) else []
    write_csv(out / "comparisons_vs_S0.csv", comparisons)
    alert_lines = alerts(rows)
    (out / "alerts.txt").write_text(
        "\n".join(alert_lines) + ("\n" if alert_lines else "nenhum alerta\n"), encoding="utf-8")
    info = {
        "test": "scipy.stats.mannwhitneyu(alternative='two-sided')",
        "correction": "Holm (implementação própria, analysis/stats.py::holm)",
        "n_comparisons": len(comparisons),
        "tested_metrics": TESTED,
        "verified_metrics": EXPECTED,
        "baseline": BASELINE,
        "percentile": "numpy.percentile(..., 95, method='linear')",
        "sd": "desvio padrão amostral (ddof = 1)",
    }
    (out / "stats_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"{len(rows)} execuções, {len(comparisons)} comparações, {len(alert_lines)} alertas -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
