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
