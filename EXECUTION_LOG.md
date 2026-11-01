# Registro de execução — Rodada preliminar (Ciclo 2)

Plano do Passo 6, seção 5. Preenchido em 2026-10-31 a partir dos logs da rodada. Os números de duração,
latência e convergência saem de `data/processed/checks_report.md` (seção "Dados para o
EXECUTION_LOG.md"), gerado por `analysis/checks.py`.

---

## 1. Identificação

| Item | Valor |
|---|---|
| Commit do código | `011052ceaaf0dcaa3c3635929a4bf0fdc0497237` (piloto e rodada) |
| Branch | `feat/prototipo` |
| Data | 2026-10-31 |
| Início da rodada | Rodada 1 (S0, S2, S4, S6, S7, S9): 2026-10-31 20:10:44 · Rodada 2, complementar (S1, S3, S5, S8, S10; D-021): 21:28:58 |
| Fim da rodada | Rodada 1: 21:28:39 (77,8 min) · Rodada 2: 22:08:22 (39,4 min). Logs: `data/raw/preliminary_20261031T201043.log` e `data/raw/preliminary_complementar_20261031T212858.log` |

## 2. Host

Valores levantados em 2026-10-31 (confirmar com o `manifest.json` do piloto, campo `host`).

| Item | Valor |
|---|---|
| SO | Windows 11 Pro 10.0.26200; experimentos dentro do WSL2 (Ubuntu 24.04.2 LTS) |
| Kernel (containers e orquestrador) | `6.6.114.1-microsoft-standard-WSL2` |
| CPU | 12th Gen Intel Core i7-12700F, 20 threads |
| Memória | 16 GB (MemTotal no WSL2: 16299064 kB) |
| Docker | Docker Engine nativo do WSL2, 29.1.3 (cliente e servidor) |
| Python | orquestrador 3.12.3 (WSL); containers 3.12.16 (`python:3.12-slim`); análise 3.13 no Windows |
| tc | iproute2-6.15.0 |

## 3. Checklist antes de começar (seção 3.1)

| Item | Situação |
|---|---|
| Testes da seção 8 passam neste host | Sim. Servidor 17, cliente 16, ponta a ponta + hash 4 (no WSL, por `preliminary.sh pilot`, 2026-10-31 20:07); análise 13 (Windows) |
| Teste "netem funcional" passou neste host | Sim. Repetido no piloto (2026-10-31 20:07): PASSOU, timeout em 10,01 s com `loss 100%`, RTT sem netem 0,14 ms; relatório `data/netem_check_20261031T200732.json` |
| Parâmetros de projeto confirmados pelo autor | Sim: DECISIONS.md, D-019 |
| Código commitado (hash na seção 1) | Sim; `git status` limpo no Windows e no WSL |
| Espaço em disco (piloto × 24) | Piloto 1284 KB → ~30 MB para 24 execuções; 233 GB livres em C: |
| Sem outra carga pesada no host | Sim (confirmado pelo autor): nada além do VS Code com a sessão do agente; Docker Desktop encerrado antes da rodada; às 21:06 só os containers `tcc-client` e `tcc-server` estavam rodando |
| Host não suspende nem hiberna | Processo temporário com `SetThreadExecutionState` (ES_SYSTEM_REQUIRED) durante a rodada, sem alterar as configurações de energia |

## 4. Execução piloto (seção 3.2)

| Item | Resultado |
|---|---|
| Diretório | `data/raw/_pilot/S0_pilot_20261031T200828_pilot` (com o `battery_20261031T200828.json` do piloto, movido para lá) |
| `manifest.json` completo | Sim: sementes (tag `pilot`), parâmetros, netem, interfaces, `same_clock` verdadeiro, versões, hardware, commit, `converged: true` |
| `client.sqlite`: 1000 eventos, todos ACKED | Sim (1000/1000) |
| `requests.jsonl` × `server_requests.jsonl` coerentes | Sim: 1000 linhas cada; 1000 requisições `ok` |
| `network_events.jsonl` (S0: `reset`, `t0`, `final`; ver D-020) | Sim: `reset`, `t0`, `final` |
| Análise do piloto: R1 = 100%, R2 = 0, C1 = C3 = C4 = 0 | Sim (`data/pilot_processed/`); também R5 = 0, SEQ_ANOMALY = 0, APPLIED_IGNORED_CONFLICT = 0 |
| Duração real | 109,6 s |

## 5. Durações

Tempo real por cenário (aquecimento + 3 execuções), de `checks_report.md`:

| Cenário | Execuções | Tempo real somado (min) |
|---|---|---|
| S0 | 4 | 7,3 |
| S1 | 4 | 7,3 |
| S2 | 4 | 7,4 |
| S3 | 4 | 7,2 |
| S4 | 4 | 7,2 |
| S5 | 4 | 7,2 |
| S6 | 4 | 41,1 |
| S7 | 4 | 7,3 |
| S8 | 4 | 8,7 |
| S9 | 4 | 7,2 |
| S10 | 4 | 8,8 |
| **Total** | 44 | **116,7** (≈ 1 h 57 min; rodadas: 77,8 + 39,4 min) |

Projeção para o Ciclo 3 (11 cenários × 11 execuções), com os mesmos tempos médios por execução:
116,7 min × 11/4 ≈ **5,3 h** de experimento (a Metodologia estimava 8–10 h).
Execução típica: ~110 s; S8 e S10: ~131 s; S6: ~620 s.

## 6. Latência do `docker exec` nas mudanças de rede

472 comandos `tc` via `docker exec` (todas as execuções, incluindo aquecimentos):
**mínimo 83,7 ms, mediana 119,2 ms, máximo 255,9 ms**. Cada mudança de rede é aplicada nos dois
containers em paralelo; o instante usado nas métricas é o fim do comando mais lento (D-015).
Em S5 e S6 a restauração ocorreu em t0 + 30,12 s e t0 + 600,2 s (alvos: 30 s e 600 s).

## 7. Interrupções, erros e ações

Nenhuma interrupção, erro de ambiente ou execução inválida (`data/raw/_invalid/` não existe).

- A rodada foi feita em duas partes com o mesmo commit: a rodada do plano (6 cenários) e,
  encadeada automaticamente logo depois, a rodada complementar (5 cenários), por decisão do autor
  (D-021).
- O `battery_*.json` do piloto foi movido para `data/raw/_pilot/` para não se misturar com as
  baterias da rodada.

## 8. Execuções que não convergiram (R3)

Nenhuma. As 33 execuções válidas e os 11 aquecimentos convergiram (R3 = 0% em todos os cenários).

## 9. Resultado das verificações (`checks_report.md`)

`data/processed/checks_report.md` (gerado com `--scenarios S0,...,S10 --reps 3`):
**33 PASSOU · 0 FALHOU · 1 NÃO CONFIRMADA**.

- **4.1 Integridade:** 3 execuções válidas + 1 aquecimento em cada um dos 11 cenários; manifestos
  completos; mesmo commit (`011052c`) nas 44 execuções; 44 sementes de cliente distintas; 1000
  eventos por execução; comandos netem iguais aos de `scenarios.json`.
- **4.2 Garantias:** R1 = 100%, R2 = 0, C1 = 0, C3 = 0, C4 = 0, SEQ_ANOMALY = 0 e
  APPLIED_IGNORED_CONFLICT = 0 nas 33 execuções.
- **4.3 Coerência:** todas confirmadas, exceto **S7: R5 > 0 → NÃO CONFIRMADA** (R5 = 0% nas 3
  execuções). Não é erro automático (seção 6 do plano): fica para o autor avaliar (ver seção 10).

## 10. Problemas e comportamentos inesperados registrados

Fatos observados e hipóteses **a confirmar pelo autor**. Não são conclusões.

| # | Observação | Onde | Situação |
|---|---|---|---|
| 1 | **Defeito encontrado no desenvolvimento:** sem TCP_NODELAY, cada resposta do servidor esperava ~40 ms (Nagle + ACK atrasado), o que dobrava o atraso medido com netem | teste netem, fase 4 | Corrigido antes dos experimentos (D-011) |
| 2 | **S7: R5 = 0%** nas 3 execuções, contra a dedução "R5 > 0" | `checks_report.md` 4.3 | NÃO CONFIRMADA. Hipótese: o TCP retransmite o pedido durante a janela offline de 5 s, e a retransmissão chega depois que a rede volta, ainda dentro do timeout de 10 s; a requisição termina `ok`, só que mais lenta (D1 p95 ≈ 6,2 s em S7). A verificar pelo autor (ex.: duração das requisições em `requests.jsonl` × fases da rede em `network_events.jsonl`) |
| 3 | **S8 e S10: D2 ≈ 22 s.** A geração termina em t0 + 99,9 s, dentro da fase offline de 90–120 s; como t_ref = último `created_at_ns` nos ciclos, D2 inclui ~20 s de espera até a rede voltar. Em S7 a última fase offline termina em t0 + 100 s, e D2 ≈ 1,8 s | `metrics_per_run.csv` × `network_events.jsonl` | Consequência da definição de D2/t_ref (D-016); descrever no texto ao apresentar D2 |
| 4 | **S9:** taxa de descarte realizada de 7,5%, 10,6% e 10,2% (67/893, 87/817, 86/847 requisições), para probabilidade configurada de 0,10 | `server_requests.jsonl` | Variação esperada de sorteio; informar a taxa realizada |
| 5 | **S0: picos de D1** (máximo de 223–348 ms por execução; mediana ≈ 22 ms; D6 = 3) sem nenhuma condição de rede | `metrics_per_run.csv` | Causa não investigada (candidatos: fsync do SQLite no WSL2, escalonamento da VM); registrar como observação |
| 6 | **D1 em S0 ≈ 20–22 ms** com RTT ≈ 0,1 ms | piloto e S0 | Hipótese: custo das gravações duráveis do SQLite (vários commits por evento); ver `DECISIONS.md`, observações |
| 7 | **S6: D2 e D3 variam muito entre execuções** (D3 de 4,3 a 12,8 s; D2 de 5,0 a 14,0 s) | `metrics_per_run.csv` | Hipótese: a fase do backoff (até 30 s) no instante da restauração; com n = 3 não há como separar |
| 8 | **Latência do `docker exec`** de 84 a 256 ms por mudança de rede | seção 6 | Limitação do ambiente, maior em proporção nas janelas de 5 s de S7 |
