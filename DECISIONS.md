# Registro de decisões

Decisões que o plano de implementação deixa em aberto. Cada entrada traz data, decisão e motivo.
Itens marcados **[CONFIRMAR]** precisam do aval do autor antes dos experimentos (fases 8 e 9).

---

## D-001 — Exceção de dependências na análise
- **Data:** 2026-10-31
- **Decisão:** `client/`, `server/` e `experiments/` usam só a biblioteca padrão. `analysis/` usa `numpy`, `scipy` e `matplotlib`, declarados em `analysis/requirements.txt`.
- **Motivo:** exceção prevista no plano (seção 0, item 5). Teste de Mann–Whitney, percentis e gráficos não justificam reimplementação.

## D-002 — Parâmetros de projeto abertos (valores padrão) [CONFIRMADO em D-019]
- **Data:** 2026-10-31
- **Decisão:** valores padrão sugeridos pelo plano, todos configuráveis por argumento ou variável de ambiente do cliente/servidor:
  - mistura de operações: CREATE 30%, UPDATE 60%, DELETE 10%;
  - campos de texto (`title`, `description`): 64 caracteres;
  - limite da fila local: 10000 eventos;
  - intervalo de verificação com fila vazia: 1 s;
  - jitter do netem: `distribution normal`, explícito no comando;
  - taxa de descarte em S9: 0,10 por requisição.
- **Motivo:** plano, seção 3 ("Parâmetros de projeto ainda abertos").

## D-003 — Branch de trabalho
- **Data:** 2026-10-31
- **Decisão:** o protótipo é desenvolvido na branch `feat/prototipo`, com um commit por fase.
- **Motivo:** manter `main` limpa até o autor revisar; commits por fase facilitam citar o commit exato no manifesto.

## D-004 — Servidor: detalhes do processamento de lote
- **Data:** 2026-10-31
- **Decisão:**
  1. O servidor ordena os eventos do lote por `seq` antes de processar (o cliente já envia em ordem; a ordenação só torna a regra 5.4 independente da ordem no JSON). A resposta lista os resultados nessa ordem.
  2. CREATE sobre `entity_id` existente **e excluído** segue a regra "CREATE existente = UPDATE com todos os campos"; como UPDATE sobre entidade excluída é ignorado, o efeito é `APPLIED_IGNORED_CONFLICT`. Com UUID4 isso não ocorre.
  3. Lote malformado (JSON inválido ou campos ausentes) recebe HTTP 400 e é registrado como `BAD_REQUEST` em `server_events.jsonl`; erro inesperado no processamento recebe HTTP 500 (`ERROR`) após rollback. O cliente trata ambos como falha (`http_error`).
  4. `client_progress` é atualizado na mesma transação dos eventos aplicados.
  5. O campo `data` é gravado como JSON compacto com chaves ordenadas.
- **Motivo:** o plano não especifica esses casos; as escolhas preservam as regras 5.4/5.5 e não afetam o caminho normal com um único cliente.

## D-005 — Servidor: sorteio de descarte (S9)
- **Data:** 2026-10-31
- **Decisão:** o sorteio `random.Random(SERVER_SEED)` é feito uma vez por `POST /sync/events` processado com sucesso, depois do commit e dentro do mesmo lock do processamento. Com `DROP_RESPONSE_RATE = 0` nenhum número é sorteado. No descarte, o handler não envia nada, define `close_connection = True` e o `socketserver` fecha o socket. Teste `server/tests/test_http.py::DropResponseTest` confirma que o cliente recebe `http.client.RemoteDisconnected`.
- **Motivo:** plano, seção 5.6. O lock torna a sequência de sorteios determinística em relação à ordem das requisições.

## D-006 — Backoff: expoente n = k − 1
- **Data:** 2026-10-31
- **Decisão:** a k-ésima falha consecutiva (k ≥ 1) espera `uniform(0, min(T_max, T_base × 2^(k−1)))` (full jitter). A primeira espera tem teto 0,5 s; o teto chega a 30 s em k = 7 (0,5 × 64 = 32 → 30). O RNG do jitter é `random.Random(jitter_seed)`, com `jitter_seed` derivado da semente da execução pelo orquestrador.
- **Motivo:** plano, seção 4.6 (torna explícito o `n` da fórmula da especificação).

## D-007 — Gerador: identificadores, campos e tamanho do payload [CONFIRMADO em D-019]
- **Data:** 2026-10-31
- **Decisão:**
  1. `event_id` e `entity_id` são UUID versão 4 gerados a partir do RNG da semente (`uuid.UUID(int=rng.getrandbits(128), version=4)`), e não de `os.urandom`. Assim a sequência inteira, inclusive os identificadores, é reprodutível.
  2. `title` e `description`: 64 caracteres de `[A-Za-z0-9]`; `value`: inteiro em [100000, 999999] (sempre 6 dígitos).
  3. O UPDATE altera um campo sorteado uniformemente entre `title`, `description` e `value`.
- **Consequência a avaliar pelo autor:** o tamanho do payload é fixo para CREATE (`payload_bytes` = 172) e DELETE (`{}` = 2 bytes), mas **não** para UPDATE: `{"title":"…64…"}` e `{"description":"…64…"}` têm 76 e 82 bytes, `{"value":123456}` tem 16. O plano diz que o comprimento fixo "torna o tamanho do payload fixo por tipo de operação", o que só vale se o UPDATE alterar sempre o mesmo campo. D5 usa os `payload_bytes` reais de cada evento, então a métrica continua correta; muda apenas a descrição no texto. Alternativas: (a) manter e descrever no texto; (b) UPDATE sempre sobre o mesmo campo (title e description também diferem entre si, 76 × 82 bytes).
- **Motivo:** plano, seção 4.4.

## D-008 — Gerador: instante t0 compartilhado
- **Data:** 2026-10-31
- **Decisão:** o orquestrador passa ao cliente `--start-at-ns`, um instante absoluto (`time.time_ns()`) um pouco no futuro. O cliente aguarda até ele e aplica a operação i em `t0 + i × 0,1 s`, medindo a espera com `time.monotonic()` (sem acumular atraso). O orquestrador agenda as mudanças de rede relativas ao mesmo t0.
- **Motivo:** o `docker exec` que inicia o cliente tem latência própria e variável; com t0 absoluto, o início da geração e o cronograma de rede ficam alinhados no relógio do kernel compartilhado (plano, seção 4.3).

## D-009 — Timeout da requisição
- **Data:** 2026-10-31
- **Decisão:** T = 10 s é o `timeout` do `http.client.HTTPConnection`, que vale para cada operação de socket (conexão, envio e cada leitura) e não para a requisição inteira.
- **Motivo:** biblioteca padrão. Como requisição e resposta cabem em poucos segmentos, na prática a requisição falha em ≈ T quando a rede some (verificado no teste "netem funcional", fase 4). Uma resposta que chegasse aos poucos poderia passar de T no total; isso não é esperado nos cenários.

## D-010 — Cliente: tratamento da resposta e encerramento
- **Data:** 2026-10-31
- **Decisão:**
  1. Uma resposta 200 válida conta como sucesso (zera as falhas consecutivas) mesmo que traga `REJECTED_GAP`/`NOT_PROCESSED`; esses eventos voltam a PENDING e são reenviados no próximo lote, sem espera.
  2. Evento do lote ausente da resposta volta a PENDING (contado como `MISSING` em `status_counts` do log).
  3. Ao iniciar, eventos IN_FLIGHT de uma execução interrompida voltam a PENDING.
  4. Código de saída: 0 = convergiu (gera `client_done.json`); 3 = interrompido por SIGTERM antes de convergir. Em ambos os casos `client_state_hashes.json` é gravado.
  5. Arquivos auxiliares além da seção 4.9: `client_info.json` (parâmetros efetivos e contagem real de operações por tipo), `generation_done.json` (t0 e último `created_at_ns`, lido pelo orquestrador para calcular t_ref) e `client.pid` (para o SIGTERM do orquestrador).
- **Motivo:** o plano não cobre esses casos; as escolhas não alteram o protocolo.

## D-011 — Servidor: TCP_NODELAY e resposta numa única escrita (correção de defeito)
- **Data:** 2026-10-31
- **Decisão:** o handler do servidor usa `disable_nagle_algorithm = True` (TCP_NODELAY) e envia cabeçalhos e corpo da resposta numa única escrita. O cliente já usa TCP_NODELAY (`http.client` liga por padrão) e já envia cabeçalhos e corpo juntos.
- **Motivo:** a primeira execução do teste "netem funcional" mostrou 44 ms por requisição **sem** netem e +400 ms (em vez de +200 ms) com `delay 100ms` em cada sentido. Causa: `BaseHTTPRequestHandler` escrevia cabeçalhos e corpo separadamente; o Nagle segurava o corpo até o ACK atrasado do cliente (~40 ms), ou um RTT a mais com netem. Isso inflaria D1–D3 em todos os cenários. Depois da correção: 0,1 ms sem netem e +200,6 ms com o delay (teste passou).

## D-012 — Docker: uma imagem para cliente e servidor
- **Data:** 2026-10-31
- **Decisão:** `docker/Dockerfile` (base `python:3.12-slim` + `iproute2`) contém os pacotes `sync_client` e `sync_server`; o compose cria dois containers a partir dela (`tcc-server` roda o servidor; `tcc-client` fica ocioso com `sleep infinity` e cada execução é iniciada por `docker exec`). Rede bridge dedicada `syncnet`, `cap_add: [NET_ADMIN]` nos dois. Os arquivos ficam em `/data` dentro de cada container (sem volume); container recriado = banco vazio.
- **Motivo:** mesma versão de Python e do código nos dois lados; plano, seção 6.1.

## D-013 — Host do autor: netem verificado; orquestrador deve rodar dentro do WSL2
- **Data:** 2026-10-31
- **Situação verificada (`experiments/netem_check.py`, ⚠ VERIFICAR das seções 6.1 e 11):** Windows 11 + Docker Desktop 29.7.2 com backend WSL2, kernel `6.6.114.1-microsoft-standard-WSL2`, `tc` iproute2-6.15.0. O `sch_netem` está disponível; a interface dos dois containers é `eth0` (detectada, não assumida). Delay +200,6 ms (esperado ~200); `loss 100%` → timeout em 10,01–10,02 s com conexão nova e com conexão keep-alive. Latência do `docker exec` a partir do Windows: 68–83 ms por comando. Repetido dentro do WSL2 (Ubuntu 24.04, Docker Engine nativo 29.1.3, mesmo kernel): delay +200,7 ms, timeouts em 10,01–10,02 s, `same_clock` verdadeiro; latência do `docker exec` 95–150 ms por comando.
- **Decisão:** nos experimentos, o orquestrador **roda dentro de uma distribuição WSL2** (Ubuntu, com a integração do Docker Desktop habilitada), e não no Python do Windows. Cada execução verifica o relógio de cada container (`clock_offset` no manifesto): o instante lido dentro do container precisa cair entre os instantes antes e depois do `docker exec` no orquestrador, em todas as amostras (`same_clock`). Se não cair, a execução é recusada (opção `--allow-clock-mismatch` só para depuração). Um limite fixo em ms não serviria: a incerteza da estimativa é metade da latência do exec (~65 ms).
- **Motivo:** o plano assume que cliente, servidor e orquestrador compartilham o relógio do kernel. No Docker Desktop os containers usam o relógio da VM do WSL2, não o do Windows. Medido a partir do Windows, o offset foi de ~26 ms ± 39 ms, o que não serve para alinhar t0 e as mudanças de rede. Todas as distribuições WSL2 rodam na mesma VM e no mesmo kernel, então dentro do Ubuntu o relógio é o mesmo dos containers.

## D-014 — Orquestrador usa a CLI do docker, não o compose
- **Data:** 2026-10-31
- **Decisão:** `experiments/dockerctl.py` cria rede e containers com `docker build`, `docker network create` e `docker run`, com os mesmos parâmetros de `docker/docker-compose.yml` (imagem, nomes `tcc-server`/`tcc-client`, alias `server`, rede bridge, `NET_ADMIN`, variáveis de ambiente). O compose fica para uso manual.
- **Motivo:** o Docker Engine nativo do WSL2 (onde o orquestrador roda, D-013) não tem o plugin `docker compose`, e a instalação exige `sudo`. A CLI básica existe em qualquer instalação do Docker.

## D-015 — Orquestrador: detalhes de execução
- **Data:** 2026-10-31
- **Decisão:**
  1. **Sementes:** `int(sha256(f"{master}|{cenário}|{repetição}|{papel}")[:8], 16)`, com papel ∈ {client, jitter, server} e repetição = `warmup` no aquecimento. Semente-mestre padrão 20261031, registrada no manifesto. Cada cenário e repetição tem carga própria (amostras independentes).  A alternativa seria a mesma carga para a repetição i de todos os cenários (desenho pareado). **Confirmado em D-019: independentes.**
  2. **t0** = instante do comando + 3 s (D-008). A condição de rede inicial é aplicada antes de t0.
  3. **Mudança de rede:** o comando é executado nos dois containers em paralelo. O instante da mudança é `t_applied_ns` = o mais tardio dos instantes "depois" (a condição vale com certeza nos dois sentidos). `t_first_before_ns` e os instantes por container também ficam em `network_events.jsonl`. Nos ciclos (S7, S8, S10) os instantes-alvo são t0 + k × meio-período, sem acumular a latência do exec.
  4. **Limite de convergência:** t_ref = último `created_at_ns` (lido de `generation_done.json`) ou, em S5/S6, o mais tardio entre ele e `restore_ns`. Passados 15 min de t_ref, o orquestrador envia SIGTERM ao cliente (PID em `/data/client.pid`) e marca `converged=false`. Há também um teto de segurança: t0 + N/taxa + interrupção + 15 min + 2 min.
  5. **Coleta:** remove o netem, lê `GET /state/hashes` (salvo em `server_state_hashes.json`), para o servidor com SIGTERM (`docker stop`, fecha o SQLite) e copia `/data` de cada container para `data/raw/<run_id>/client/` e `.../server/`. Na raiz da execução ficam `manifest.json`, `network_events.jsonl`, `server_state_hashes.json` e `client_stdout.log`.
  6. `converged` = cliente saiu com código 0, gravou `client_done.json` e não foi encerrado pelo limite.
  7. Cada bateria grava `battery_<timestamp>.json` com as execuções, erros e o tempo real decorrido (fase 8).
  8. `--n-events` e `--no-warmup` existem só para testes do protótipo; o orquestrador avisa quando N ≠ 1000.
- **Motivo:** plano, seções 6.4 e 6.5, nos pontos em que o plano deixa a implementação em aberto.

## D-016 — Análise: definições operacionais das métricas
- **Data:** 2026-10-31
- **Decisão:**
  1. **D2** só é calculado em execuções convergidas; nas demais fica vazio (NaN), e a falha entra em R3.
  2. **D3:** as restaurações são os registros `restore` (S5/S6) e `online` (S7, S8, S10) de `network_events.jsonl`, no instante `t_applied_ns` (D-015). A fila é considerada não vazia em r se existe evento com `created_at_ns ≤ r` e `acked_at_ns` nulo ou `> r`. Restauração sem requisição `ok` posterior é ignorada. `D3_n` registra quantas restaurações entraram na média.
  3. **D4** = N ÷ D2, com N = eventos em `client.events` (1000).
  4. **D6:** na varredura, quando criação e ACK têm o mesmo instante, o ACK é processado primeiro.
  5. **C1** conta `event_id` com status `APPLIED` em mais de uma linha de `server_requests.jsonl` (inclui requisições com resposta descartada).
  6. Desvio padrão amostral (ddof = 1).
- **Motivo:** plano, seção 7.1, nos pontos em que a definição deixa margem.

## D-017 — Análise: métricas testadas e número de comparações [CONFIRMAR]
- **Data:** 2026-10-31
- **Decisão:** cada cenário S1–S10 é comparado com S0 (Mann–Whitney bilateral) nas métricas por execução R4, R5, D1 (mediana, p95 e máximo), D2, D3, D5 e D6, sempre que os dois grupos têm valores. D3 não existe em S0 e D4 só existe em S6, então nenhuma das duas entra em comparação (ambas são apenas descritas). R3 é por cenário e não é testada. A correção de Holm é aplicada sobre **todas** as comparações realizadas, e o número fica em `stats_info.json`. Com 11 cenários completos: 10 cenários × 8 métricas = 80 comparações. Quando os dois grupos têm todos os valores iguais (ex.: R5 = 0 em S0 e S1), o teste é indefinido; registra-se p = 1 com nota.
- **Motivo:** o plano diz "cada métrica por execução" mas não lista quais; testar as três estatísticas de D1 aumenta as comparações e reduz o poder após Holm. O autor deve confirmar a lista de acordo com as hipóteses da Metodologia.
- **R1, R2, C1, C3 e C4** não são testadas (valor esperado fixo). Qualquer desvio, execução não convergida, `APPLIED_IGNORED_CONFLICT`, `SEQ_ANOMALY` ou `QUEUE_FULL` gera alerta em `alerts.txt`.

## D-018 — Gráficos
- **Data:** 2026-10-31
- **Decisão:** uma série por gráfico, na mesma cor (azul `#2a78d6`), com grade e eixos discretos. Boxplot de D1 em escala logarítmica (os cenários vão de dezenas de ms a dezenas de s). Barras de D2 e D3 com média ± desvio padrão. A série temporal da fila tem uma linha por execução, com o tempo relativo a t0.
- **Motivo:** figuras para impressão em LaTeX (PDF vetorial + PNG).

## Observações das execuções de aceite (fases 5–7)
- **Data:** 2026-10-31
- **S0, N = 1000** (Docker no WSL2): convergiu em 110 s de tempo real; R1 = 100%, R2 = 0, R4 = 1,0, R5 = 0%, C1 = C3 = C4 = 0, D1 mediana 18,5 ms, p95 27,0 ms, máx. 40,7 ms, D5 = 7,77, D6 = 1. Sem netem, D1 ≈ 18 ms vem principalmente das gravações duráveis do SQLite (vários commits com fsync por evento, no cliente e no servidor), e não da rede (RTT ≈ 0,1 ms). Vale descrever isso no texto ao interpretar D1.
- **S9, N = 1000** (fase 6, descarte de resposta em Docker): o servidor descartou 68 de 901 respostas (7,5% realizados, com taxa configurada de 10%; sorteio com semente). O cliente registrou exatamente 68 `remote_disconnected`, reenviou, recebeu 83 `DUPLICATE` (C2) e terminou com C1 = 0, C3 = 0, C4 = 0, R1 = 100%.

## D-019 — Confirmações do autor (antes da rodada preliminar)
- **Data:** 2026-10-31
- **Decisão (confirmada pelo autor):**
  1. **D-002:** padrões de projeto mantidos: mistura CREATE 30% / UPDATE 60% / DELETE 10%, campos de texto com 64 caracteres, limite da fila de 10000 eventos, intervalo de verificação de 1 s.
  2. **D-007:** gerador mantido (UPDATE altera um campo sorteado; payload de 16, 76 ou 82 bytes). O **texto do TCC** será ajustado para dizer que o tamanho é fixo por campo, e não por tipo de operação.
  3. **D-015:** sementes independentes por cenário e repetição (amostras independentes).
- **Pendente:** D-017 (métricas testadas) só é necessário na bateria completa, porque a rodada preliminar é apenas descritiva. Ver `PENDENCIAS.md`.

## D-020 — Ferramentas da rodada preliminar (Plano do Passo 6)
- **Data:** 2026-10-31
- **Decisão:**
  1. **Marcador t0:** `network_events.jsonl` ganha um registro `t0` (`marker: true`, sem comando tc) com a condição de rede vigente. Em S0 o arquivo traz `reset` (remoção preventiva do netem), `t0` e `final` (remoção no fim); `reset` e `final` são comandos `tc qdisc del` reais e ficam registrados porque o plano pede o instante de todo comando.
  2. **Piloto:** `run_experiment.py --pilot` roda sem aquecimento e grava em `data/raw/_pilot/`, com sementes próprias (`seed_tag = "pilot"`). `is_pilot` fica no manifesto.
  3. **Retomada após interrupção:** `--reps-list 2,3 --seed-tag <rótulo>` roda só as repetições que faltam, com sementes novas (o rótulo entra na derivação, D-015, e no `run_id`).
  4. **`git_dirty`** considera só as pastas de código (`client`, `server`, `experiments`, `docker`, `analysis`). Documentação como `EXECUTION_LOG.md` pode ser editada durante a rodada sem invalidar o manifesto.
  5. **`metrics.py --in data/raw --out data/processed`** grava `metrics_per_run.csv` e `summary_preliminary.csv`. Este tem uma linha por cenário e métrica, com os valores individuais (`value_1..value_n`, na ordem das repetições, e `run_ids`), média, mínimo e máximo. R3 aparece como linha própria. O desvio padrão fica de fora (n = 3).
  6. **`plots.py --in data/processed`:** D1 (mediana por execução), D2 e D3 como pontos individuais + traço da média. O boxplot de D1 só é gerado com n ≥ 5 (bateria completa). Série da fila em S6 (e S8, se houver).
  7. **`checks.py`** (seção 4 do plano). Critérios operacionais que o plano não fixa: "S2 maior que S0" e "S4 maior que S0" = o menor valor do cenário é maior que o maior valor de S0 (comparação descritiva, sem teste). "D6 muito menor que 1000" em S2 = D6 ≤ 100 (10% de N) em todas as execuções. Em S6, o limite de D3 usa a latência medida da mudança `restore` daquela execução. Os critérios são escolhas do agente, estão escritos no relatório e podem ser trocados pelo autor (ver `PENDENCIAS.md`).
  8. `stats.py` não é executado na rodada preliminar (n = 3: o menor p exato bilateral do Mann–Whitney é 0,10).
- **Motivo:** Plano do Passo 6, seções 3, 4 e 7.
