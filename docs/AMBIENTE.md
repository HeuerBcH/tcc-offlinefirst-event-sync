# Registro do ambiente experimental (Artefato 6)

Versões, hardware e parâmetros do ambiente. Os valores de cada execução ficam também no seu
`manifest.json` (fonte de verdade por execução); este documento consolida o que é comum a todas.
Levantamento: 2026-10-31.

## Hardware e sistema

| Item | Valor |
|---|---|
| CPU | 12th Gen Intel Core i7-12700F, 20 threads |
| Memória | 16 GB (16299064 kB visíveis no WSL2) |
| SO do host | Windows 11 Pro 10.0.26200 |
| Ambiente Linux | WSL2, Ubuntu 24.04.2 LTS, kernel `6.6.114.1-microsoft-standard-WSL2` |
| Docker | Docker Engine nativo do WSL2, 29.1.3 (cliente e servidor); sem compose (DECISIONS.md, D-014) |
| Relógio | orquestrador e containers no mesmo kernel; verificado a cada execução (`clock_offset.same_clock`, D-013) |

## Software

| Componente | Versão |
|---|---|
| Imagem dos containers | `python:3.12-slim` + `iproute2` → Python 3.12.16, `tc` iproute2-6.15.0 |
| Orquestrador | Python 3.12.3 (WSL2), só biblioteca padrão |
| Cliente e servidor | só biblioteca padrão (`sqlite3`, `http.client`, `http.server`) |
| Análise | Python 3.13 (Windows) com numpy 2.3.4, scipy 1.16.2, matplotlib 3.10.7 (`analysis/requirements.txt`) |

## Rede

- Rede bridge dedicada (`tccsync_syncnet`); interface `eth0` nos dois containers (detectada, não assumida).
- `tc netem` na saída de cada container, aplicado via `docker exec` (`experiments/dockerctl.py`).
- Teste "netem funcional" (`experiments/netem_check.py`), no WSL2: +200,7 ms com `delay 100ms` em
  cada sentido; timeout em 10,0 s com `loss 100%`; RTT sem netem ≈ 0,1 ms.
- Latência do `docker exec` por comando tc: 95–150 ms no teste netem e 113–254 ms nas execuções de
  aceite. O valor da rodada fica em `EXECUTION_LOG.md`.

## Parâmetros

Fixos pela Metodologia e pela especificação (plano do protótipo, seção 3):

| Parâmetro | Valor |
|---|---|
| Clientes por execução / requisições simultâneas | 1 / 1 |
| Eventos por execução (N) | 1000 |
| Taxa de geração | 10 eventos/s (t0 + i × 0,1 s) |
| Lote máximo (B) | 50 |
| Timeout (T) | 10 s (por operação de socket, D-009) |
| Backoff | full jitter, uniforme em [0, min(30, 0,5 × 2^(k−1))] s; sem limite de tentativas |
| Limite de convergência | 15 min após t_ref |
| Repetições | 3 (Ciclo 2) ou 10 (Ciclo 3), + 1 aquecimento por cenário |

De projeto, confirmados pelo autor (D-019): mistura CREATE 30% / UPDATE 60% / DELETE 10%;
campos de texto com 64 caracteres; limite da fila de 10000; verificação a cada 1 s; jitter do
netem `distribution normal`; descarte em S9 com probabilidade 0,10 por requisição.

Cenários: [`experiments/scenarios.json`](../experiments/scenarios.json) (Metodologia, Quadro 3).

## Scripts

| Script | Função |
|---|---|
| `experiments/netem_check.py` | teste "netem funcional" |
| `experiments/run_experiment.py` | orquestrador: sobe containers, aplica cenários, roda e coleta |
| `experiments/dockerctl.py` | comandos docker e netem, com os instantes de cada comando |
| `experiments/preliminary.sh` | rodada preliminar (piloto e rodada) |
| `analysis/metrics.py` | métricas por execução, resumo preliminar e exportação para CSV |
| `analysis/export_raw.py` | dados brutos em CSV |
| `analysis/checks.py` | verificações da rodada |
| `analysis/plots.py` | gráficos |
| `analysis/stats.py` | estatística (só na bateria completa) |
| `docs/arquitetura.py` | diagrama da arquitetura (Artefato 5) |
