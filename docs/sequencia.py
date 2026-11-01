"""Gera o diagrama de sequência do mecanismo (Artefato 1) em docs/sequencia.pdf e docs/sequencia.png.

    python docs/sequencia.py      # requer matplotlib (analysis/requirements.txt)

Reflete o protótipo implementado: gravação atômica, lote, deduplicação, ordem por seq, LWW,
confirmação e reenvio com backoff.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

OUT = Path(__file__).resolve().parent
INK = "#0b0b0b"
INK_2 = "#52514e"
BLUE = "#2a78d6"
DB_BG = "#cde2fb"
ALT = "#b3471d"

PARTS = [  # (x, título, subtítulo, banco?)
    (8, "Usuário /", "gerador", False),
    (29, "Fila local", "SQLite do cliente", True),
    (50, "Sincronizador", "cliente", False),
    (75, "Servidor", "handler + processador", False),
    (96, "Banco", "SQLite do servidor", True),
]
X = {name: x for name, (x, *_rest) in zip(("user", "queue", "sync", "server", "db"), PARTS)}

fig, ax = plt.subplots(figsize=(12, 11))
ax.set_xlim(-1, 106)
ax.set_ylim(0, 100)
ax.axis("off")

TOP, BOTTOM = 93, 1.5
for x, title, sub, db in PARTS:
    ax.add_patch(FancyBboxPatch((x - 8, TOP), 16, 5.5, boxstyle="round,pad=0.2,rounding_size=0.8",
                                facecolor=DB_BG if db else "white", edgecolor=BLUE if db else INK_2,
                                linewidth=1.1))
    ax.text(x, TOP + 3.7, title, ha="center", va="center", fontsize=9, fontweight="bold", color=INK)
    ax.text(x, TOP + 1.6, sub, ha="center", va="center", fontsize=7.3, color=INK_2)
    ax.plot([x, x], [BOTTOM, TOP - 0.3], color="#bdbcb6", linewidth=1, linestyle=(0, (4, 3)), zorder=0)


def msg(y, a, b, text, dashed=False, color=INK, above=True):
    xa, xb = X[a], X[b]
    ax.add_patch(FancyArrowPatch((xa, y), (xb, y), arrowstyle="-|>", mutation_scale=10, color=color,
                                 linewidth=1.1, linestyle="--" if dashed else "-"))
    ax.text((xa + xb) / 2, y + (0.9 if above else -0.9), text, ha="center",
            va="bottom" if above else "top", fontsize=7.6, color=color)


def self_note(y, who, lines, color=INK_2, width=19):
    x = X[who]
    h = 1.9 * len(lines) + 0.8
    ax.add_patch(FancyBboxPatch((x - width / 2, y - h), width, h, boxstyle="round,pad=0.25,rounding_size=0.6",
                                facecolor="#f5f5f3", edgecolor="#d6d5d0", linewidth=0.8, zorder=2))
    for i, line in enumerate(lines):
        ax.text(x, y - 1.3 - i * 1.9, line, ha="center", va="center", fontsize=7.2, color=color, zorder=3)


def frame(y_top, y_bot, label, guard):
    ax.add_patch(Rectangle((2, y_bot), 102, y_top - y_bot, fill=False, edgecolor=ALT, linewidth=1))
    ax.add_patch(Rectangle((2, y_top - 2.4), 6, 2.4, facecolor=ALT, edgecolor=ALT))
    ax.text(5, y_top - 1.2, label, ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
    ax.text(9.5, y_top - 1.2, guard, ha="left", va="center", fontsize=7.4, color=ALT, style="italic")


# 1. gravação local
msg(89, "user", "queue", "operação (CREATE / UPDATE / DELETE)")
self_note(87.4, "queue", ["transação atômica:", "estado + evento PENDING", "seq = next_seq"], width=20)
msg(78.5, "queue", "sync", "sinal (novo evento)", dashed=True)

# 2. lote
msg(75, "sync", "queue", "lê até 50 eventos PENDING (seq crescente)")
self_note(73.4, "queue", ["IN_FLIGHT, attempts + 1", "horário de envio"], width=20)
msg(66.5, "sync", "server", "POST /sync/events  (lote JSON)")

# 3. processamento no servidor
self_note(64.5, "server", ["para cada evento, por seq:", "event_id já aplicado → DUPLICATE",
                           "seq = último + 1 → aplica (LWW) → APPLIED",
                           "seq > último + 1 → REJECTED_GAP", "(restantes: NOT_PROCESSED)"], width=27)
msg(51.5, "server", "db", "transação + commit")
msg(48.5, "server", "sync", "200 {results, last_applied_seq}", dashed=True)
msg(45.5, "sync", "queue", "APPLIED / DUPLICATE → ACKED;  demais → PENDING")
self_note(43.9, "queue", ["ACKED: horário de confirmação", "(removível; mantido para auditoria)"], width=24)

# 4. falha e reenvio
frame(37.5, 3, "alt", "falha: timeout (10 s), conexão perdida, resposta descartada (S9) ou HTTP ≠ 200")
msg(32.3, "sync", "server", "POST /sync/events  (lote)")
ax.text(X["server"] - 6.5, 29.6, "✕ sem resposta", ha="center", fontsize=7.6, color=ALT)
msg(27.5, "sync", "queue", "lote inteiro → PENDING")
self_note(26, "sync", ["k = falhas consecutivas", "espera uniforme em", "[0, min(30, 0,5 × 2^(k−1))] s"],
          width=22)
msg(17, "sync", "server", "reenvia o lote (mesmos event_id)")
self_note(15.3, "server", ["eventos já aplicados → DUPLICATE", "(sem efeito no estado)"], width=26)
msg(8.5, "server", "sync", "200 {results}", dashed=True)
msg(5.5, "sync", "queue", "→ ACKED")

for ext in ("pdf", "png"):
    fig.savefig(OUT / f"sequencia.{ext}", dpi=200, bbox_inches="tight")
print(f"diagrama em {OUT / 'sequencia.pdf'} e .png")
