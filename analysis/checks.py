"""Verificações automáticas da rodada (Plano do Passo 6, seção 4). Não altera nenhum dado.

    python analysis/checks.py [--raw data/raw] [--processed data/processed]
                              [--scenarios S0,S2,S4,S6,S7,S9] [--reps 3]

Grava <processed>/checks_report.md com:
  4.1 integridade da rodada, 4.2 garantias, 4.3 coerência com o desenho do mecanismo e
  dados para o EXECUTION_LOG.md (durações, latência do docker exec, não convergências).

Status: PASSOU / FALHOU (4.1 e 4.2: defeito ou achado, seguir a seção 6 do plano) /
NÃO CONFIRMADA (4.3: não é erro automático; registrar para o autor) / N/A (sem dados).
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = ROOT / "experiments" / "scenarios.json"

# Parâmetros fixos usados nas deduções (plano do protótipo, seção 3).
N_EVENTS = 1000
T_TIMEOUT_S = 10.0
T_MAX_S = 30.0
# Critério operacional para "D6 muito menor que 1000" em S2 (escolha do agente; ver relatório).
S2_D6_LIMIT = 100

REQUIRED_MANIFEST = [
    "run_id", "scenario", "is_warmup", "seeds", "parameters", "netem_commands", "interfaces",
    "converged", "operation_counts", "git_commit", "python_version", "docker_version", "host",
    "tc_version", "master_seed", "timings", "client_parameters",
]
REQUIRED_HOST = ["uname_r", "cpu_model", "mem_total"]

PASS, FAIL, UNCONFIRMED, NA = "PASSOU", "FALHOU", "NÃO CONFIRMADA", "N/A"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def fmt(v, digits=3):
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        return f"{v:.{digits}f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)


class Report:
    def __init__(self):
        self.sections = []

    def section(self, title):
        self.sections.append({"title": title, "rows": [], "notes": []})

    def check(self, name, status, detail):
        self.sections[-1]["rows"].append((name, status, detail))

    def note(self, text):
        self.sections[-1]["notes"].append(text)

    def counts(self):
        return Counter(status for s in self.sections for _, status, _ in s["rows"])

    def render(self, header):
        lines = header[:]
        for s in self.sections:
            lines += ["", f"## {s['title']}", ""]
            if s["rows"]:
                lines += ["| Verificação | Status | Detalhe |", "|---|---|---|"]
                for name, status, detail in s["rows"]:
                    detail = str(detail).replace("|", "\\|").replace("\n", "<br>")
                    lines.append(f"| {name} | **{status}** | {detail} |")
            for n in s["notes"]:
                lines += ["", n]
        return "\n".join(lines) + "\n"


def load_manifests(directory):
    out = []
    if directory.exists():
        for m in sorted(directory.glob("*/manifest.json")):
            out.append((m.parent, read_json(m)))
    return out


def expected_commands(scenario, offline_spec, interfaces):
    specs = {"constant": [scenario["online"]],
             "initial_outage": [offline_spec, scenario["online"]],
             "cycles": [scenario["online"], offline_spec]}[scenario["type"]]
    cmds = set()
    for iface in set(interfaces.values()):
        cmds.add(f"tc qdisc del dev {iface} root")
        for spec in specs:
            if spec is not None:
                cmds.add(f"tc qdisc replace dev {iface} root netem {spec}")
    return cmds


def exec_latencies_ms(run_dir):
    """Duração de cada comando tc via docker exec (t_after − t_before), em ms."""
    out = []
    for rec in read_jsonl(run_dir / "network_events.jsonl"):
        for c in rec.get("commands", []):
            out.append((c["t_after_ns"] - c["t_before_ns"]) / 1e6)
    return out


def change_latency_s(run_dir, label):
    """Maior latência de uma mudança de rede com o rótulo dado (t_applied − t_first_before)."""
    recs = [r for r in read_jsonl(run_dir / "network_events.jsonl") if r["label"] == label]
    return max(((r["t_applied_ns"] - r["t_first_before_ns"]) / 1e9 for r in recs), default=math.nan)


def s9_duplicates_after_drop(run_dir):
    """Eventos APPLIED em requisições descartadas e quantos deles aparecem depois como DUPLICATE."""
    log = read_jsonl(run_dir / "server" / "server_requests.jsonl")
    dropped_applied = []  # (índice da requisição, event_id)
    for i, req in enumerate(log):
        if req.get("dropped"):
            dropped_applied += [(i, e["event_id"]) for e in req["events"] if e["status"] == "APPLIED"]
    dup_positions = defaultdict(list)
    for i, req in enumerate(log):
        for e in req["events"]:
            if e["status"] == "DUPLICATE":
                dup_positions[e["event_id"]].append(i)
    missing = [eid for i, eid in dropped_applied if not any(j > i for j in dup_positions[eid])]
    n_dropped = sum(1 for r in log if r.get("dropped"))
    return n_dropped, len(dropped_applied), missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", "--in", dest="raw", default="data/raw")
    ap.add_argument("--processed", default="data/processed")
    ap.add_argument("--scenarios", default="S0,S2,S4,S6,S7,S9")
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args(argv)
    raw, processed = Path(args.raw), Path(args.processed)
    expected_sc = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    scen_def = read_json(SCENARIOS_FILE)
    offline_spec, scenarios = scen_def["offline_spec"], scen_def["scenarios"]

    metrics_path = processed / "metrics_per_run.csv"
    if not metrics_path.exists():
        print(f"{metrics_path} não existe; rode antes analysis/metrics.py", file=sys.stderr)
        return 1
    with open(metrics_path, newline="", encoding="utf-8") as fh:
        metrics = list(csv.DictReader(fh))
    by_run = {r["run_id"]: r for r in metrics}
    by_sc = defaultdict(list)
    for r in metrics:
        by_sc[r["scenario"]].append(r)

    runs = load_manifests(raw)
    valid = [(d, m) for d, m in runs if not m.get("is_warmup") and m.get("converged") is not None]
    errored = [(d, m) for d, m in runs if m.get("converged") is None]
    warmups = load_manifests(raw / "_warmup")
    rep = Report()

    # ---------------------------------------------------------------- 4.1 integridade
    rep.section("4.1 Integridade da rodada")
    for sc in expected_sc:
        nv = sum(1 for _, m in valid if m["scenario"] == sc)
        nw = sum(1 for _, m in warmups if m["scenario"] == sc)
        ok = nv == args.reps and nw == 1
        rep.check(f"Execuções {sc}", PASS if ok else FAIL,
                  f"{nv} válidas (esperado {args.reps}), {nw} aquecimento(s) (esperado 1)")
    extra = sorted({m["scenario"] for _, m in valid} - set(expected_sc))
    if extra:
        rep.check("Cenários fora do escopo", FAIL, f"encontrados: {', '.join(extra)}")
    rep.check("Execuções interrompidas (sem `converged`)", PASS if not errored else FAIL,
              "nenhuma" if not errored else
              "; ".join(d.name for d, _ in errored) + " — erro de ambiente: mover para `_invalid/` "
              "com nota e repetir com nova semente (seção 6)")

    incomplete = []
    for d, m in valid + warmups:
        missing = [k for k in REQUIRED_MANIFEST if m.get(k) in (None, "", [], {})
                   and not (k == "converged" and m.get(k) is False)]
        missing += [f"host.{k}" for k in REQUIRED_HOST if not m.get("host", {}).get(k)]
        if not m.get("is_warmup") and m.get("repetition") is None:
            missing.append("repetition")
        if missing:
            incomplete.append(f"{d.name}: {', '.join(missing)}")
    rep.check("Manifestos completos", PASS if not incomplete else FAIL,
              "todos os campos da seção 6.5 presentes" if not incomplete else "; ".join(incomplete))

    commits = Counter(m.get("git_commit") for _, m in valid + warmups)
    dirty = [d.name for d, m in valid + warmups if m.get("git_dirty")]
    rep.check("Mesmo commit Git", PASS if len(commits) == 1 and not dirty else FAIL,
              ", ".join(f"`{c}` ({n})" for c, n in commits.items())
              + (f"; com alterações não commitadas: {', '.join(dirty)}" if dirty else ""))

    seeds = Counter(tuple(sorted(m["seeds"].items())) for _, m in valid + warmups)
    client_seeds = Counter(m["seeds"]["client"] for _, m in valid + warmups)
    dup = [s for s, n in client_seeds.items() if n > 1]
    rep.check("Sementes distintas", PASS if not dup and max(seeds.values(), default=1) == 1 else FAIL,
              f"{len(client_seeds)} sementes de cliente distintas em {sum(client_seeds.values())} execuções"
              + (f"; repetidas: {dup}" if dup else ""))

    wrong_n = [f"{r['run_id']}: {r['n_events']}" for r in metrics if int(float(r["n_events"])) != N_EVENTS]
    rep.check("1000 eventos por execução (cliente)", PASS if not wrong_n else FAIL,
              f"todas as {len(metrics)} execuções" if not wrong_n else "; ".join(wrong_n))

    bad_net = []
    for d, m in valid + warmups:
        exp = expected_commands(scenarios[m["scenario"]], offline_spec, m["interfaces"])
        got = set(m.get("netem_commands", []))
        if got != exp:
            bad_net.append(f"{d.name}: faltando {sorted(exp - got)}, a mais {sorted(got - exp)}")
    rep.check("Comandos netem = cenários (seção 6.3)", PASS if not bad_net else FAIL,
              "comandos de todos os manifestos iguais aos de `experiments/scenarios.json`"
              if not bad_net else "; ".join(bad_net))

    # ---------------------------------------------------------------- 4.2 garantias
    rep.section("4.2 Garantias (valor fixo em todas as execuções)")
    guarantees = [("R1_pct", 100.0, "R1 = 100%"), ("R2", 0, "R2 = 0"), ("C1", 0, "C1 = 0"),
                  ("C3", 0, "C3 = 0"), ("C4", 0, "C4 = 0"),
                  ("seq_anomalies", 0, "SEQ_ANOMALY = 0"),
                  ("applied_ignored_conflict", 0, "APPLIED_IGNORED_CONFLICT = 0")]
    for col, expected, label in guarantees:
        dev = [f"{r['run_id']}: {r[col]}" for r in metrics if fnum(r[col]) != expected]
        rep.check(label, PASS if not dev else FAIL,
                  f"todas as {len(metrics)} execuções" if not dev else
                  "; ".join(dev) + " — parar a análise e investigar (seção 6)")

    # ---------------------------------------------------------------- 4.3 coerência
    rep.section("4.3 Coerência com o desenho do mecanismo")
    rep.note("Deduções do desenho, não valores medidos. NÃO CONFIRMADA não é erro automático: "
             "registrar para o autor, com os valores observados.")

    def vals(sc, col):
        return [fnum(r[col]) for r in by_sc.get(sc, [])]

    def lst(v):
        return "[" + ", ".join(fmt(x) for x in v) + "]"

    def coherent(name, sc_needed, cond, detail):
        if any(not by_sc.get(s) for s in sc_needed):
            rep.check(name, NA, "sem execuções de " + ", ".join(s for s in sc_needed if not by_sc.get(s)))
        else:
            rep.check(name, PASS if cond() else UNCONFIRMED, detail())

    coherent("S0: R5 = 0", ["S0"], lambda: all(v == 0 for v in vals("S0", "R5_pct")),
             lambda: f"R5 (%) por execução: {lst(vals('S0', 'R5_pct'))}")
    coherent("S2: mediana de D1 > S0", ["S0", "S2"],
             lambda: min(vals("S2", "D1_median_ms")) > max(vals("S0", "D1_median_ms")),
             lambda: f"critério: menor valor de S2 > maior valor de S0. D1 mediana (ms) S2 "
                     f"{lst(vals('S2', 'D1_median_ms'))}; S0 {lst(vals('S0', 'D1_median_ms'))}")
    coherent("S2: D6 muito menor que 1000", ["S2"],
             lambda: max(vals("S2", "D6")) <= S2_D6_LIMIT,
             lambda: f"critério operacional: D6 ≤ {S2_D6_LIMIT} (10% de N) em todas as execuções. "
                     f"D6: {lst(vals('S2', 'D6'))}")
    coherent("S4: p95 de D1 > S0", ["S0", "S4"],
             lambda: min(vals("S4", "D1_p95_ms")) > max(vals("S0", "D1_p95_ms")),
             lambda: f"critério: menor valor de S4 > maior valor de S0. D1 p95 (ms) S4 "
                     f"{lst(vals('S4', 'D1_p95_ms'))}; S0 {lst(vals('S0', 'D1_p95_ms'))}")
    coherent("S6: D6 = 1000", ["S6"], lambda: all(v == N_EVENTS for v in vals("S6", "D6")),
             lambda: f"D6: {lst(vals('S6', 'D6'))}")

    s6_rows = []
    for d, m in valid:
        if m["scenario"] == "S6" and m["run_id"] in by_run:
            lat = change_latency_s(d, "restore")
            limit = T_TIMEOUT_S + T_MAX_S + lat
            s6_rows.append((m["run_id"], fnum(by_run[m["run_id"]]["D3_s"]), limit, lat))
    coherent("S6: D3 ≤ T + T_max + latência do docker exec", ["S6"],
             lambda: all(d3 <= lim for _, d3, lim, _ in s6_rows),
             lambda: "; ".join(f"{rid}: D3 = {fmt(d3)} s, limite = 10 + 30 + {fmt(lat)} = {fmt(lim)} s"
                               for rid, d3, lim, lat in s6_rows))
    coherent("S7: R5 > 0", ["S7"], lambda: all(v > 0 for v in vals("S7", "R5_pct")),
             lambda: f"R5 (%) por execução: {lst(vals('S7', 'R5_pct'))}")

    s9 = []
    for d, m in valid:
        if m["scenario"] == "S9" and m["run_id"] in by_run:
            n_drop, n_applied_dropped, missing = s9_duplicates_after_drop(d)
            s9.append((m["run_id"], n_drop, n_applied_dropped, missing,
                       fnum(by_run[m["run_id"]]["C2"])))
    coherent("S9: requisições descartadas > 0", ["S9"], lambda: all(x[1] > 0 for x in s9),
             lambda: "; ".join(f"{x[0]}: {x[1]} descartadas" for x in s9))
    coherent("S9: APPLIED em requisição descartada reaparece como DUPLICATE", ["S9"],
             lambda: all(not x[3] for x in s9),
             lambda: "; ".join(f"{x[0]}: {x[2]} eventos APPLIED em descartadas, {len(x[3])} sem DUPLICATE posterior"
                               for x in s9))
    coherent("S9: C2 ≥ APPLIED em requisições descartadas", ["S9"],
             lambda: all(x[4] >= x[2] for x in s9),
             lambda: "; ".join(f"{x[0]}: C2 = {fmt(x[4])}, APPLIED em descartadas = {x[2]}" for x in s9))

    # ---------------------------------------------------------------- dados para o EXECUTION_LOG
    rep.section("Dados para o EXECUTION_LOG.md")
    lines = ["| Cenário | Execuções (válidas + aquec.) | Tempo real somado (min) | Convergiram |",
             "|---|---|---|---|"]
    total_s = 0.0
    for sc in sorted({m["scenario"] for _, m in valid + warmups}, key=lambda s: (len(s), s)):
        ms = [m for _, m in valid + warmups if m["scenario"] == sc]
        wall = sum(fnum(m.get("wall_time_s")) for m in ms if not math.isnan(fnum(m.get("wall_time_s"))))
        total_s += wall
        conv = sum(1 for m in ms if m.get("converged"))
        lines.append(f"| {sc} | {len(ms)} | {wall / 60:.1f} | {conv}/{len(ms)} |")
    lines.append(f"| **Total** | {len(valid) + len(warmups)} | {total_s / 60:.1f} | |")
    rep.note("\n".join(lines))

    batteries = sorted(raw.glob("battery_*.json"))
    if batteries:
        bl = ["Baterias (`battery_*.json`):", ""]
        for b in batteries:
            info = read_json(b)
            errs = [r["run_id"] for r in info.get("runs", []) if "error" in r]
            bl.append(f"- `{b.name}`: início {info.get('started_at')}, fim {info.get('finished_at', '— (interrompida?)')}, "
                      f"{fmt(fnum(info.get('elapsed_s')) / 60, 1)} min, {len(info.get('runs', []))} execuções"
                      + (f", erros: {', '.join(errs)}" if errs else ""))
        rep.note("\n".join(bl))

    lat = [x for d, _ in valid + warmups for x in exec_latencies_ms(d)]
    if lat:
        rep.note(f"Latência do `docker exec` por comando tc ({len(lat)} comandos): mínimo {min(lat):.1f} ms, "
                 f"mediana {statistics.median(lat):.1f} ms, máximo {max(lat):.1f} ms.")
    nonconv = [(d, m) for d, m in valid if not m.get("converged")]
    if nonconv:
        nl = ["Execuções que não convergiram (R3):", ""]
        for d, m in nonconv:
            final = [r for r in read_jsonl(d / "network_events.jsonl") if r["label"] == "final"]
            nl.append(f"- `{d.name}`: encerrada pelo limite = {m.get('client_killed_by_limit')}, "
                      f"código de saída = {m.get('client_exit_code')}, erro na condução da rede = "
                      f"{m.get('network_driver_error')}, netem removido no fim = {bool(final)}")
        rep.note("\n".join(nl))
    else:
        rep.note("Todas as execuções válidas convergiram (R3 = 0% em todos os cenários).")

    counts = rep.counts()
    header = [
        "# Relatório de verificações — rodada preliminar (Ciclo 2)",
        "",
        f"Gerado por `analysis/checks.py` em {datetime.now().isoformat(timespec='seconds')}. "
        f"Fonte: `{raw.as_posix()}` e `{metrics_path.as_posix()}`. Nenhum dado foi alterado.",
        "",
        f"Resumo: {counts.get(PASS, 0)} PASSOU · {counts.get(FAIL, 0)} FALHOU · "
        f"{counts.get(UNCONFIRMED, 0)} NÃO CONFIRMADA · {counts.get(NA, 0)} N/A",
    ]
    out = processed / "checks_report.md"
    out.write_text(rep.render(header), encoding="utf-8")
    print(f"{out}: {dict(counts)}")
    return 1 if counts.get(FAIL) else 0


if __name__ == "__main__":
    sys.exit(main())
