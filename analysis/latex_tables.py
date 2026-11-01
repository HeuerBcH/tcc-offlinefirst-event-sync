"""Tabelas LaTeX dos resultados por cenário, para o Overleaf.

    python analysis/latex_tables.py [--in data/processed] [--out data/tables]

Lê metrics_per_run.csv e grava, em <out>/:
  tabela_cenarios.tex        cenários e condição de rede (experiments/scenarios.json)
  tabela_confiabilidade.tex  R1, R2, R3, R4, R5
  tabela_desempenho_latencia.tex     D1 (mediana, p95, máximo)
  tabela_desempenho_recuperacao.tex  D2, D3, D4, D5, D6
  tabela_consistencia.tex    C1, C2, C3, C4
Cada célula traz a média e, entre parênteses, o mínimo e o máximo das execuções (com n = 3, o
desvio padrão pouco informa). Requer \\usepackage{booktabs} e \\usepackage{graphicx} no preâmbulo. Decimais com vírgula.
As legendas só descrevem o conteúdo; a interpretação fica no texto. Abaixo de cada tabela vem a
linha de fonte (macro \\fonteautor do modelo, SOURCE) e depois a nota.
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Macro do modelo do TCC no Overleaf ("Fonte: Elaborado pelo autor"), igual à dos quadros e figuras.
SOURCE = "\\fonteautor"


def scenario_key(s):
    return (len(s), s)


def fmt_num(v, digits):
    if v is None or math.isnan(v):
        return "--"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")  # 1.234,5 (pt-BR)


def auto_digits(v):
    a = abs(v)
    return 0 if a >= 100 else 1 if a >= 10 else 2


def cell(values, digits=None, integer=False):
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return "--"
    mean, lo, hi = sum(vals) / len(vals), min(vals), max(vals)
    if integer and all(v == int(v) for v in vals):
        if lo == hi:
            return fmt_num(lo, 0)
        return f"{fmt_num(mean, 1)} ({fmt_num(lo, 0)}--{fmt_num(hi, 0)})"
    d = digits if digits is not None else auto_digits(mean)
    if lo == hi:
        return fmt_num(lo, d)
    return f"{fmt_num(mean, d)} ({fmt_num(lo, d)}--{fmt_num(hi, d)})"


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_sc = defaultdict(list)
    for r in rows:
        by_sc[r["scenario"]].append(r)
    return {sc: by_sc[sc] for sc in sorted(by_sc, key=scenario_key)}


def col(rows, name):
    out = []
    for r in rows:
        try:
            out.append(float(r[name]))
        except (TypeError, ValueError):
            out.append(math.nan)
    return out


def table(caption, label, header, body, note, colspec, fit_width=True):
    lines = [
        "% Gerado por analysis/latex_tables.py a partir de data/processed/metrics_per_run.csv",
        "\\begin{table}[htbp]",
        "\\centering",
        "\\small",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        *(["\\resizebox{\\textwidth}{!}{%"] if fit_width else []),
        f"\\begin{{tabular}}{{{colspec}}}",
        "\\toprule",
        " & ".join(header) + " \\\\",
        "\\midrule",
        *[" & ".join(r) + " \\\\" for r in body],
        "\\bottomrule",
        "\\end{tabular}" + ("}" if fit_width else ""),
        "",
        SOURCE,
        f"\\par\\smallskip{{\\footnotesize Nota: {note}\\par}}",
        "\\end{table}",
        "",
    ]
    return "\n".join(lines)


def n_note(by_sc):
    ns = sorted({len(v) for v in by_sc.values()})
    n = ns[0] if len(ns) == 1 else f"{ns[0]}--{ns[-1]}"
    return (f"Média de {n} execuções por cenário; entre parênteses, mínimo e máximo. "
            "Valor único quando todas as execuções coincidem.")


def scenarios_table(scen_def):
    sc = scen_def["scenarios"]
    off = scen_def["offline_spec"]
    body = []
    for sid in sorted(sc, key=scenario_key):
        s = sc[sid]
        online = s["online"] or "sem netem"
        if s["type"] == "constant":
            cond = online
        elif s["type"] == "initial_outage":
            cond = f"{off} de $t_0$ a $t_0+{s['outage_s']}$\\,s; depois {online}"
        else:
            cond = f"ciclos {s['online_s']}\\,s online ({online}) / {s['offline_s']}\\,s {off}"
        if s.get("drop_response_rate"):
            cond += f"; servidor descarta a resposta com probabilidade {fmt_num(s['drop_response_rate'], 2)}"
        cond = cond.replace("%", "\\%")
        body.append([sid, f"\\texttt{{{cond}}}" if s["type"] == "constant" and s["online"] else cond])
    return table("Cenários de rede avaliados", "tab:cenarios", ["Cenário", "Condição de rede"], body,
                 "Parâmetros do \\texttt{tc netem}, aplicados na saída dos containers do cliente e do servidor. "
                 "Na distribuição normal, o segundo valor do atraso é o parâmetro de variação (jitter), "
                 "não um intervalo fechado.", "lp{12cm}", fit_width=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="processed", default="data/processed")
    ap.add_argument("--out", default="data/tables")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    by_sc = load(Path(args.processed) / "metrics_per_run.csv")
    note = n_note(by_sc)

    (out / "tabela_cenarios.tex").write_text(
        scenarios_table(json.loads((ROOT / "experiments" / "scenarios.json").read_text(encoding="utf-8"))),
        encoding="utf-8")

    body = []
    for sc, rows in by_sc.items():
        r3 = sum(1 for r in rows if r["converged"] != "True") / len(rows) * 100
        body.append([sc, cell(col(rows, "R1_pct"), 1), cell(col(rows, "R2"), integer=True),
                     fmt_num(r3, 1), cell(col(rows, "R4"), 3), cell(col(rows, "R5_pct"), 1)])
    (out / "tabela_confiabilidade.tex").write_text(table(
        "Métricas de confiabilidade por cenário", "tab:confiabilidade",
        ["Cenário", "R1 (\\%)", "R2 (eventos)", "R3 (\\%)", "R4 (tentativas/evento)", "R5 (\\%)"],
        body, note + " R3 é calculada por cenário.", "lrrrrr"), encoding="utf-8")

    body = []
    for sc, rows in by_sc.items():
        body.append([sc, cell(col(rows, "D1_median_ms")), cell(col(rows, "D1_p95_ms")),
                     cell(col(rows, "D1_max_ms"))])
    (out / "tabela_desempenho_latencia.tex").write_text(table(
        "Métricas de desempenho por cenário: latência de sincronização por evento (D1)",
        "tab:desempenho-latencia",
        ["Cenário", "D1 mediana (ms)", "D1 p95 (ms)", "D1 máximo (ms)"],
        body, note, "lrrr", fit_width=False), encoding="utf-8")

    body = []
    for sc, rows in by_sc.items():
        body.append([sc, cell(col(rows, "D2_s"), 2), cell(col(rows, "D3_s"), 2),
                     cell(col(rows, "D4_events_per_s"), 1), cell(col(rows, "D5"), 2),
                     cell(col(rows, "D6"), integer=True)])
    (out / "tabela_desempenho_recuperacao.tex").write_text(table(
        "Métricas de desempenho por cenário: convergência, recuperação, vazão, overhead e fila (D2--D6)",
        "tab:desempenho-recuperacao",
        ["Cenário", "D2 (s)", "D3 (s)", "D4 (ev./s)", "D5", "D6 (eventos)"],
        body, note + " D3 só existe nos cenários com restauração da rede (S5--S8, S10); D4 só em S6. "
        "``--'' indica métrica não aplicável ao cenário.", "lrrrrr"), encoding="utf-8")

    body = []
    for sc, rows in by_sc.items():
        body.append([sc, cell(col(rows, "C1"), integer=True), cell(col(rows, "C2"), integer=True),
                     cell(col(rows, "C3"), integer=True), cell(col(rows, "C4"), integer=True)])
    (out / "tabela_consistencia.tex").write_text(table(
        "Métricas de consistência por cenário", "tab:consistencia",
        ["Cenário", "C1 (duplicados aplicados)", "C2 (respostas DUPLICATE)", "C3 (fora de ordem)",
         "C4 (entidades divergentes)"],
        body, note, "lrrrr"), encoding="utf-8")
    print(f"tabelas LaTeX em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
