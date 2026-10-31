"""Gera o diagrama da arquitetura (Artefato 5) em docs/arquitetura.pdf e docs/arquitetura.png.

    python docs/arquitetura.py      # requer matplotlib (analysis/requirements.txt)
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent
INK = "#0b0b0b"
INK_2 = "#52514e"
BLUE = "#2a78d6"
BLUE_BG = "#eef4fc"
GRAY_BG = "#f5f5f3"
DB_BG = "#cde2fb"

fig, ax = plt.subplots(figsize=(12, 7))
ax.set_xlim(0, 120)
ax.set_ylim(0, 70)
ax.axis("off")


def box(x, y, w, h, title, lines=(), face="white", edge=INK_2, lw=1.0, title_size=9.5, dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2",
                                facecolor=face, edgecolor=edge, linewidth=lw,
                                linestyle="--" if dashed else "-"))
    ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=title_size,
            color=INK, fontweight="bold")
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 5.6 - i * 2.7, line, ha="center", va="top", fontsize=7.8, color=INK_2)


def arrow(x1, y1, x2, y2, label=None, lx=None, ly=None, both=False, color=INK, ls="-", ha="center"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="<|-|>" if both else "-|>",
                                 mutation_scale=11, color=color, linewidth=1.2, linestyle=ls))
    if label:
        ax.text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2,
                label, ha=ha, va="center", fontsize=7.6, color=INK_2,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.2})


# Containers (os logs ficam em /data dentro de cada container)
box(2, 14, 50, 50, "Container tcc-client", face=BLUE_BG, edge=BLUE, lw=1.4, title_size=10.5)
box(68, 14, 50, 50, "Container tcc-server", face=BLUE_BG, edge=BLUE, lw=1.4, title_size=10.5)

# Cliente
box(5, 48, 21, 10, "Gerador", ["operações determinísticas", "10 eventos/s, por semente"])
box(29, 48, 21, 10, "Sincronizador", ["lotes ≤ 50, 1 requisição", "por vez; backoff 0,5–30 s"])
box(5, 27, 45, 16, "SQLite do cliente (client.sqlite)",
    ["entities: estado local · events: fila persistente",
     "PENDING → IN_FLIGHT → ACKED",
     "criação, envio, ACK (ns) e tentativas por evento"],
    face=DB_BG, edge=BLUE)
box(5, 16.5, 45, 8, "Logs do cliente", ["requests.jsonl · client_events.jsonl · hashes"], face=GRAY_BG)
arrow(15.5, 48, 15.5, 43.6, "transação atômica", lx=15.5, ly=45.8)
arrow(39.5, 43.6, 39.5, 48, "lote / resultado", lx=39.5, ly=45.8, both=True)
arrow(26, 53, 29, 53)

# Servidor
box(71, 48, 21, 10, "Handler HTTP", ["POST /sync/events", "GET /health, /state/hashes"])
box(95, 48, 21, 10, "Processador", ["dedup. por event_id", "ordem por seq · LWW"])
box(71, 27, 45, 16, "SQLite do servidor (server.sqlite)",
    ["applied_events · client_progress · entities",
     "uma transação por lote",
     "commit antes da resposta"],
    face=DB_BG, edge=BLUE)
box(71, 16.5, 45, 8, "Logs do servidor", ["server_requests.jsonl · server_events.jsonl"], face=GRAY_BG)
arrow(92, 53, 95, 53)
arrow(105.5, 48, 105.5, 43.6)
ax.text(81.5, 46.0, "S9: descarta 10% das respostas", ha="center", fontsize=7.2,
        color="#b3471d", style="italic")

# Rede
arrow(50.6, 53, 70.4, 53, both=True)
ax.text(60, 50.6, "HTTP/1.1", ha="center", fontsize=7.6, color=INK)
ax.text(60, 48.6, "lotes JSON", ha="center", fontsize=7.2, color=INK_2)
for x in (55.5, 64.5):
    ax.add_patch(FancyBboxPatch((x - 3.2, 56), 6.4, 3, boxstyle="round,pad=0.2,rounding_size=0.6",
                                facecolor="#fff4e5", edgecolor="#eda100", linewidth=1))
    ax.text(x, 57.5, "netem", ha="center", va="center", fontsize=7, color=INK)
ax.text(60, 67.5, "tc netem na saída (egress) de cada container: atraso, perda e desconexão",
        ha="center", fontsize=8, color=INK_2)

# Orquestrador
box(46.5, 1, 27, 9, "Orquestrador (host, WSL2)", ["aplica cenários · inicia · coleta"],
    dashed=True, title_size=8.8)
arrow(46.5, 5.5, 30, 13.6, "docker exec", lx=37, ly=8.2, color=INK_2, ls="--")
arrow(73.5, 5.5, 90, 13.6, "docker exec", lx=83, ly=8.2, color=INK_2, ls="--")

for ext in ("pdf", "png"):
    fig.savefig(OUT / f"arquitetura.{ext}", dpi=200, bbox_inches="tight")
print(f"diagrama em {OUT / 'arquitetura.pdf'} e .png")
