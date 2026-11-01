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
from scipy.stats import PermutationMethod, mannwhitneyu

BASELINE = "S0"
# Valor-p exato por permutação: com n_resamples acima do número de partições (C(20, 10) = 184756
# para 10 + 10), o scipy enumera todas, e o p é exato também com empates. O padrão do scipy
# (method="auto") usaria a aproximação normal com n >= 8 ou com empates (DECISIONS.md, D-023).
EXACT = PermutationMethod(n_resamples=10**6)
# Métricas testadas contra S0 (Mann–Whitney bilateral), por família = dimensão da pergunta de
# pesquisa (DECISIONS.md, D-017). Holm é aplicado dentro de cada família. Descritas, não testadas:
# D1 máximo (depende de um único evento), D3 (não existe em S0), D4 (só S6), R3 (por cenário).
FAMILIES = {
    "confiabilidade": ["R4", "R5_pct"],
    "desempenho": ["D1_median_ms", "D1_p95_ms", "D2_s", "D5", "D6"],
    "consistencia": ["C2"],
}
TESTED = [m for metrics in FAMILIES.values() for m in metrics]
FAMILY_OF = {m: f for f, metrics in FAMILIES.items() for m in metrics}
DESCRIBED = TESTED + ["D1_max_ms", "D3_s", "R1_pct", "R2", "D3_n", "D4_events_per_s", "C1", "C3",
                      "C4", "n_requests", "wall_time_s"]
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


def compare(rows, scope="family"):
    comparisons = []
    for sc in scenario_order(rows):
        if sc == BASELINE:
            continue
        for metric in TESTED:
            a, b = values(rows, sc, metric), values(rows, BASELINE, metric)
            if not a or not b:
                continue
            if len(set(a) | set(b)) == 1:
                # Empate total (ex.: R5 = 0 nos dois grupos): teste indefinido. Registra p = 1 e a
                # comparação continua na contagem do Holm (regra fixada antes da coleta, D-017).
                stat, p, note = math.nan, 1.0, "valores idênticos nos dois grupos; p = 1"
            else:
                res = mannwhitneyu(a, b, alternative="two-sided", method=EXACT)
                stat, p, note = float(res.statistic), float(res.pvalue), ""
            comparisons.append({
                "family": FAMILY_OF[metric], "scenario": sc, "metric": metric,
                "n_scenario": len(a), "n_baseline": len(b),
                "median_scenario": float(np.median(a)), "median_baseline": float(np.median(b)),
                "median_diff": float(np.median(a) - np.median(b)),
                "U": stat, "p": p, "note": note,
            })
    apply_holm(comparisons, scope)
    return comparisons


def apply_holm(comparisons, scope="family"):
    """Holm dentro de cada família (padrão, D-017) ou sobre todas as comparações (scope="all")."""
    groups = defaultdict(list)
    for c in comparisons:
        groups[c["family"] if scope == "family" else "todas"].append(c)
    for group in groups.values():
        for c, p_adj in zip(group, holm([c["p"] for c in group])):
            c["holm_group"] = c["family"] if scope == "family" else "todas"
            c["holm_m"] = len(group)
            c["p_holm"] = p_adj
            c["significant_0_05"] = p_adj < 0.05


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
    ap.add_argument("--holm-scope", choices=["family", "all"], default="family",
                    help="family (padrão, D-017): Holm dentro de cada dimensão; all: sobre todas")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.metrics)

    write_csv(out / "summary_by_scenario.csv", summarize(rows))
    comparisons = (compare(rows, args.holm_scope)
                   if any(r["scenario"] == BASELINE for r in rows) else [])
    write_csv(out / "comparisons_vs_S0.csv", comparisons)
    alert_lines = alerts(rows)
    (out / "alerts.txt").write_text(
        "\n".join(alert_lines) + ("\n" if alert_lines else "nenhum alerta\n"), encoding="utf-8")
    info = {
        "test": "scipy.stats.mannwhitneyu(alternative='two-sided', method=PermutationMethod(n_resamples=10**6)): "
                "valor-p exato por enumeração de todas as permutações, válido com empates",
        "correction": "Holm (implementação própria, analysis/stats.py::holm)",
        "holm_scope": args.holm_scope,
        "hypotheses": "H0: a distribuição da métrica no cenário é igual à de S0; "
                      "H1: é diferente (bilateral)",
        "ties_rule": "empate total nos dois grupos: p = 1, mantido na contagem do Holm",
        "n_comparisons": len(comparisons),
        "n_comparisons_by_family": {f: sum(1 for c in comparisons if c["family"] == f) for f in FAMILIES},
        "families": FAMILIES,
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
