# Registro de execução — Rodada preliminar (Ciclo 2)

Plano do Passo 6, seção 5. Preencha os campos marcados _(preencher)_. Os números de duração,
latência e convergência saem de `data/processed/checks_report.md` (seção "Dados para o
EXECUTION_LOG.md"), gerado por `analysis/checks.py`.

---

## 1. Identificação

| Item | Valor |
|---|---|
| Commit do código | _(preencher: impresso por `bash experiments/preliminary.sh round`; igual ao `git_commit` dos manifestos)_ |
| Branch | `feat/prototipo` |
| Data | _(preencher)_ |
| Início da rodada | _(preencher: 1ª linha de `data/raw/preliminary_<timestamp>.log`)_ |
| Fim da rodada | _(preencher: última linha do mesmo log)_ |

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
| Testes da seção 8 passam neste host | Passaram em 2026-10-31 (servidor 17, cliente 16, ponta a ponta + hash 4, análise 13). Repetidos por `preliminary.sh pilot`: _(preencher)_ |
| Teste "netem funcional" passou neste host | Passou em 2026-10-31 no WSL2: +200,7 ms com delay de 100 ms por sentido; timeout em 10,0 s com `loss 100%` (DECISIONS.md, D-013). Repetido no piloto: _(preencher)_ |
| Parâmetros de projeto confirmados pelo autor | Sim: DECISIONS.md, D-019 |
| Código commitado (hash na seção 1) | _(preencher)_ |
| Espaço em disco (piloto × 24) | _(preencher: impresso por `preliminary.sh pilot`)_ |
| Sem outra carga pesada no host | _(preencher)_ |
| Host não suspende nem hiberna | _(preencher: ver PENDENCIAS.md, A.1)_ |

## 4. Execução piloto (seção 3.2)

| Item | Resultado |
|---|---|
| Diretório | `data/raw/_pilot/<run_id>` _(preencher)_ |
| `manifest.json` completo | _(preencher)_ |
| `client.sqlite`: 1000 eventos, todos ACKED | _(preencher)_ |
| `requests.jsonl` × `server_requests.jsonl` coerentes | _(preencher)_ |
| `network_events.jsonl` (S0: `reset`, `t0`, `final`; ver D-020) | _(preencher)_ |
| Análise do piloto: R1 = 100%, R2 = 0, C1 = C3 = C4 = 0 | _(preencher)_ |
| Duração real | _(preencher: `wall_time_s` do manifesto)_ |

## 5. Durações

_(preencher a partir de `checks_report.md`: tabela por cenário e total)_

## 6. Latência do `docker exec` nas mudanças de rede

_(preencher a partir de `checks_report.md`: mínimo, mediana e máximo)_

Referência anterior à rodada: 95–150 ms por comando (teste netem no WSL2) e 113–254 ms nas
execuções de aceite S0/S9.

## 7. Interrupções, erros e ações

_(preencher: hora, o que aconteceu, o que foi feito. Execuções inválidas vão para
`data/raw/_invalid/` com uma nota, e nunca são apagadas)_

## 8. Execuções que não convergiram (R3)

_(preencher a partir de `checks_report.md`, com o motivo aparente)_

## 9. Resultado das verificações (`checks_report.md`)

_(preencher: resumo PASSOU / FALHOU / NÃO CONFIRMADA e o que fazer com cada FALHOU ou
NÃO CONFIRMADA, conforme a seção 6 do plano)_
