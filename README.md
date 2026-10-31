# tcc-offlinefirst-event-sync

Protótipo do TCC **"Sincronização Baseada em Eventos para Aplicações Offline-First"**.

## Objetivo

Implementar o mecanismo de sincronização baseado em eventos e o ambiente que o avalia sob
condições de rede emuladas, gerando automaticamente os dados das 15 métricas do TCC.

- **Cliente** (`client/`): grava cada operação do usuário em SQLite numa transação atômica
  (estado local + evento na fila) e sincroniza em lotes de até 50 eventos, uma requisição por
  vez, com backoff exponencial com full jitter.
- **Servidor** (`server/`): aplica os eventos com deduplicação por `event_id`, ordem estrita por
  `seq` e regra de conflito LWW; pode descartar respostas após o commit (cenário S9).
- **Ambiente** (`docker/`, `experiments/`): cliente e servidor em containers separados;
  `tc netem` aplicado na saída de cada container pelo orquestrador.
- **Análise** (`analysis/`): métricas por execução, estatística por cenário e gráficos.

Não é um produto: sem interface gráfica, autenticação, múltiplos tipos de entidade nem
sincronização do servidor para o cliente. As decisões de projeto estão em [`DECISIONS.md`](DECISIONS.md).

## Requisitos do host

- Linux com o módulo `sch_netem` no kernel, Docker e Python 3.12 (o orquestrador usa só a
  biblioteca padrão).
- **Windows:** rode o orquestrador **dentro do WSL2** (testado com Ubuntu 24.04 e o Docker Engine
  nativo do WSL). O Python do Windows não compartilha o relógio dos containers
  (DECISIONS.md, D-013); o orquestrador verifica isso a cada execução e recusa iniciar se o
  relógio não for o mesmo.
- Análise: Python 3 com `pip install -r analysis/requirements.txt` (pode ser no Windows).

## Como subir o ambiente e verificar o netem

```bash
python3 experiments/netem_check.py          # constrói a imagem, sobe os containers e testa o netem
```

O teste confirma que `delay 100ms` em cada sentido acrescenta ~200 ms a uma requisição e que
`loss 100%` leva a requisição ao timeout de 10 s. **Se falhar, o host não suporta o ambiente.**
O relatório fica em `data/netem_check.json`.

Para subir os containers manualmente: `docker compose -f docker/docker-compose.yml up -d --build`
(o orquestrador não usa o compose; ver D-014).

## Testes

```bash
python -m unittest discover -s server/tests
python -m unittest discover -s client/tests
python -m unittest discover -s tests            # hash cliente = servidor; ponta a ponta local (N = 100)
python -m unittest discover -s analysis/tests   # requer numpy/scipy
```

## Como rodar uma execução e uma bateria

```bash
# uma execução de S0 (mais o aquecimento)
python3 experiments/run_experiment.py --scenarios S0 --reps 1 --out data/raw

# rodada preliminar (Ciclo 2)
python3 experiments/run_experiment.py --scenarios S0,S2,S4,S6,S7,S9 --reps 3 --out data/raw

# bateria completa (Ciclo 3): 11 cenários × 10 execuções + 1 aquecimento por cenário
python3 experiments/run_experiment.py --scenarios S0,S1,S2,S3,S4,S5,S6,S7,S8,S9,S10 --reps 10 --out data/raw
```

Cenários em [`experiments/scenarios.json`](experiments/scenarios.json) (Metodologia, Quadro 3).
Parâmetros fixos: N = 1000 eventos a 10 eventos/s, lote 50, timeout 10 s, backoff 0,5–30 s,
limite de convergência de 15 min após t_ref. `--n-events` e `--no-warmup` existem só para testar o
protótipo.

## Onde ficam os dados

```
data/raw/
  battery_<timestamp>.json          # execuções da bateria, erros e tempo real decorrido
  _warmup/<run_id>/                 # aquecimentos (excluídos da análise)
  <run_id>/                         # ex.: S6_r03_20261031T193916
    manifest.json                   # cenário, sementes, parâmetros, netem, versões, hardware, converged
    network_events.jsonl            # cada mudança de rede, com instantes antes/depois do comando
    server_state_hashes.json        # GET /state/hashes ao fim da execução
    client_stdout.log
    client/  client.sqlite requests.jsonl client_events.jsonl client_state_hashes.json
             client_done.json generation_done.json client_info.json
    server/  server.sqlite server_requests.jsonl server_events.jsonl
data/processed/                     # metrics_per_run.csv, summary_by_scenario.csv,
                                    # comparisons_vs_S0.csv, alerts.txt, stats_info.json
data/figures/                       # PDF e PNG
```

## Como gerar métricas e gráficos

```bash
python analysis/metrics.py --raw data/raw          # -> data/processed/metrics_per_run.csv
python analysis/stats.py                           # -> resumo, comparações com S0 (Mann–Whitney + Holm), alertas
python analysis/plots.py --raw data/raw            # -> data/figures/*.pdf, *.png
```

## Mapa entre arquivos e métricas

| Métrica | Arquivos usados |
|---|---|
| R1, R2 | `server/server.sqlite` (`applied_events`), `client/client.sqlite` (`events`) |
| R3 | `manifest.json` (`converged`), por cenário |
| R4 | `client/client.sqlite` (`events.attempts`) |
| R5 | `client/requests.jsonl` (`outcome`) |
| D1 | `client/client.sqlite` (`acked_at_ns − created_at_ns`) |
| D2 | `client/client.sqlite` (`max(acked_at_ns)`, último `created_at_ns`) + `network_events.jsonl` (restauração) |
| D3 | `network_events.jsonl` (restaurações) + `client/requests.jsonl` (`finished_at_ns` da 1ª requisição `ok`) + `client/client.sqlite` (fila não vazia) |
| D4 | D2 em S6 |
| D5 | `client/requests.jsonl` (`bytes_sent`, `bytes_recv`) + `client/client.sqlite` (`payload_bytes`) |
| D6 | `client/client.sqlite` (`created_at_ns`, `acked_at_ns`) |
| C1, C2 | `server/server_requests.jsonl` (status por evento em cada requisição) |
| C3 | `server/server.sqlite` (`applied_events` por `applied_at_ns`) |
| C4 | `client/client_state_hashes.json` × `server_state_hashes.json` |
