"""Gráficos para o texto do TCC (plano, seção 7.4), em PDF e PNG.

    python analysis/plots.py [--in data/processed] [--raw data/raw] [--out data/figures]

- d1_median_points: mediana de D1 de cada execução, por cenário (boxplot só com n >= 5);
- d2_points, d3_points: valor de cada execução e média, por cenário;
- queue_<S6|S8>: tamanho da fila (criados − ACKED) ao longo do tempo, uma linha por execução.
"""
import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import find_runs, load_run, queue_series  # noqa: E402
from stats import load_rows, scenario_order, to_float  # noqa: E402

SERIES = "#2a78d6"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK_2, "axes.labelcolor": INK, "xtick.color": INK_2,
    "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "savefig.bbox": "tight", "pdf.fonttype": 42,
})


def save(fig, out, name):
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{name}.{ext}", dpi=200)
    plt.close(fig)


def per_scenario(rows, metric):
    data = {}
    for sc in scenario_order(rows):
        v = [to_float(r[metric]) for r in rows if r["scenario"] == sc]
        v = [x for x in v if not math.isnan(x)]
        if v:
            data[sc] = v
    return data


def boxplot(rows, out):
    data = per_scenario(rows, "D1_median_ms")
    if not data:
        return
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.boxplot(list(data.values()), tick_labels=list(data), widths=0.5, patch_artist=True,
               boxprops={"facecolor": "#cde2fb", "edgecolor": SERIES, "linewidth": 1},
               medianprops={"color": SERIES, "linewidth": 2},
               whiskerprops={"color": SERIES}, capprops={"color": SERIES},
               flierprops={"marker": "o", "markersize": 3, "markerfacecolor": SERIES,
                           "markeredgecolor": "none"})
    ax.set_yscale("log")
    ax.set_xlabel("Cenário")
    ax.set_ylabel("D1, mediana por execução (ms)")
    ax.set_title("Escala logarítmica", loc="left", color=INK_2, fontsize=8)
    save(fig, out, "d1_median_boxplot")


def dots(rows, metric, ylabel, out, name, log=False):
    """Valores individuais por cenário (um ponto por execução) e a média como traço.

    Usado na rodada preliminar (n = 3), em que boxplot e desvio padrão pouco informam.
    """
    data = per_scenario(rows, metric)
    if not data:
        return
    fig, ax = plt.subplots(figsize=(6, 3))
    for x, (sc, v) in enumerate(data.items()):
        offsets = np.linspace(-0.12, 0.12, len(v)) if len(v) > 1 else [0.0]
        ax.scatter([x + o for o in offsets], v, s=28, color=SERIES, edgecolors="white",
                   linewidths=0.8, zorder=3, label="execução" if x == 0 else None)
        ax.hlines(np.mean(v), x - 0.25, x + 0.25, color=INK, linewidth=1.5, zorder=2,
                  label="média" if x == 0 else None)
    ax.set_xticks(range(len(data)), list(data))
    ax.set_xlim(-0.6, len(data) - 0.4)
    if log:
        ax.set_yscale("log")
        ax.set_title("Escala logarítmica", loc="left", color=INK_2, fontsize=8)
    ax.set_xlabel("Cenário")
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, fontsize=8, loc="best")
    save(fig, out, name)


def queue_plot(raw, scenario, out):
    runs = [d for d in find_runs(raw) if d.name.startswith(f"{scenario}_")]
    if not runs:
        return
    fig, ax = plt.subplots(figsize=(6, 3))
    for d in runs:
        run = load_run(d)
        t0 = run["manifest"]["timings"]["t0_ns"]
        series = queue_series(run["events"])
        t = [(p[0] - t0) / 1e9 for p in series]
        size = [p[1] for p in series]
        ax.step(t, size, where="post", color=SERIES, linewidth=1, alpha=0.6)
    ax.set_xlabel("Tempo desde t0 (s)")
    ax.set_ylabel("Eventos na fila (criados − ACKED)")
    ax.set_title(f"{scenario}: tamanho da fila ({len(runs)} execuções)", loc="left", color=INK)
    save(fig, out, f"queue_{scenario}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="processed", default="data/processed",
                    help="diretório com metrics_per_run.csv")
    ap.add_argument("--raw", default="data/raw", help="execuções brutas (para a série da fila)")
    ap.add_argument("--metrics", default=None, help="caminho alternativo de metrics_per_run.csv")
    ap.add_argument("--out", default="data/figures")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.metrics or Path(args.processed) / "metrics_per_run.csv")
    max_n = max(len(v) for v in per_scenario(rows, "D1_median_ms").values()) if rows else 0
    dots(rows, "D1_median_ms", "D1, mediana por execução (ms)", out, "d1_median_points", log=True)
    if max_n >= 5:
        boxplot(rows, out)  # bateria completa (n = 10)
    dots(rows, "D2_s", "D2: tempo até esvaziar a fila (s)", out, "d2_points")
    dots(rows, "D3_s", "D3: tempo de retomada (s)", out, "d3_points")
    for sc in ("S6", "S8"):
        queue_plot(args.raw, sc, out)
    print(f"figuras em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
