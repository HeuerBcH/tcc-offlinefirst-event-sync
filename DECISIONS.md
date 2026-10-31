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
