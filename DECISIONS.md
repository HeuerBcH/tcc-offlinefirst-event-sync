# Registro de decisões

Decisões que o plano de implementação deixa em aberto. Cada entrada traz data, decisão e motivo.
Itens marcados **[CONFIRMAR]** precisam do aval do autor antes dos experimentos (fases 8 e 9).

---

## D-001 — Exceção de dependências na análise
- **Data:** 2026-10-31
- **Decisão:** `client/`, `server/` e `experiments/` usam só a biblioteca padrão. `analysis/` usa `numpy`, `scipy` e `matplotlib`, declarados em `analysis/requirements.txt`.
- **Motivo:** exceção prevista no plano (seção 0, item 5). Teste de Mann–Whitney, percentis e gráficos não justificam reimplementação.

## D-002 — Parâmetros de projeto abertos (valores padrão) [CONFIRMAR]
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

## D-007 — Gerador: identificadores, campos e tamanho do payload [CONFIRMAR]
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
- **Situação verificada (`experiments/netem_check.py`, ⚠ VERIFICAR das seções 6.1 e 11):** Windows 11 + Docker Desktop 29.7.2 com backend WSL2, kernel `6.6.114.1-microsoft-standard-WSL2`, `tc` iproute2-6.15.0. O `sch_netem` está disponível; a interface dos dois containers é `eth0` (detectada, não assumida). Delay +200,6 ms (esperado ~200); `loss 100%` → timeout em 10,01–10,02 s com conexão nova e com conexão keep-alive. Latência do `docker exec` a partir do Windows: 68–83 ms por comando.
- **Decisão:** nos experimentos, o orquestrador **roda dentro de uma distribuição WSL2** (Ubuntu, com a integração do Docker Desktop habilitada), e não no Python do Windows. Cada execução mede a diferença entre o relógio do orquestrador e o de cada container (`clock_offset` no manifesto); o orquestrador recusa iniciar se a diferença passar de 5 ms (opção `--allow-clock-offset` para depuração).
- **Motivo:** o plano assume que cliente, servidor e orquestrador compartilham o relógio do kernel. No Docker Desktop os containers usam o relógio da VM do WSL2, não o do Windows. Medido a partir do Windows, o offset foi de ~26 ms ± 39 ms, o que não serve para alinhar t0 e as mudanças de rede. Todas as distribuições WSL2 rodam na mesma VM e no mesmo kernel, então dentro do Ubuntu o relógio é o mesmo dos containers.
