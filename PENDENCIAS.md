# Pendências até a conclusão do estudo

Lista do que falta fazer, em ordem, até o estudo poder ser considerado concluído. Marque
`[x]` ao concluir. Detalhes de cada decisão estão em [`DECISIONS.md`](DECISIONS.md) (referências
D-0xx); o registro da rodada vai em [`EXECUTION_LOG.md`](EXECUTION_LOG.md).

Situação em 2026-10-31, 22h: protótipo concluído; **rodada preliminar do Ciclo 2 concluída com os 11
cenários × 3 execuções** (commit `011052c`); 33 PASSOU, 0 FALHOU e 1 NÃO CONFIRMADA (S7: R5 > 0).
Ver `EXECUTION_LOG.md`.

---

## 0. Artefatos dos Passos 4 a 6

- [x] Artefato 4: repositório Git + README.
- [x] Artefato 5: diagrama da arquitetura (`docs/arquitetura.pdf`/`.png`).
- [x] Artefato 6: scripts do experimento + registro do ambiente (`docs/AMBIENTE.md` e `manifest.json` de cada execução).
- [x] Artefato 7: dados brutos em `data/raw/` (JSONL + SQLite) e em CSV em `data/processed/raw_csv/`.
- [ ] Artefato 8: tabela (`summary_preliminary.csv` + tabelas LaTeX em `data/tables/`) e gráficos
      (`data/figures/`) prontos; **faltam as observações iniciais, escritas pelo autor**.
- [x] Artefato 1, complemento: diagrama de sequência (`docs/sequencia.pdf`/`.png`).

---

## A. Rodada preliminar (Ciclo 2, fase 8): o próximo passo

### A.1 Preparar o host (seção 3.1 do Plano do Passo 6)

- [x] **Impedir suspensão e hibernação no Windows** durante ~2 h. Configurações → Sistema →
      Energia → "Nunca" para suspensão e tela, ou em um PowerShell:
      `powercfg /change standby-timeout-ac 0` e `powercfg /change hibernate-timeout-ac 0`
      (para voltar depois: o mesmo comando com o valor anterior, ex.: `30`).
- [x] Fechar programas pesados (jogos, navegador com muitas abas, IDE indexando, backup,
      Windows Update em andamento) e **não usar o PC** durante a rodada.
- [x] Docker Desktop **não** é usado nos experimentos (o orquestrador usa o Docker nativo do
      Ubuntu no WSL, D-013/D-014). Se estiver aberto, feche para não disputar CPU.
- [x] Manter aberto o terminal do Ubuntu (WSL) que roda a rodada; fechá-lo pode encerrar o WSL.
- [x] Conferir que não há alterações de código pendentes (`git status`). O script recusa
      rodar com alterações em `client/`, `server/`, `experiments/`, `docker/` ou `analysis/`.

### A.2 Execução piloto (seção 3.2)

No terminal do Ubuntu (WSL):

```bash
cd /mnt/c/Users/berna/Documents/Clones/tcc-offlinefirst-event-sync
bash experiments/preliminary.sh pilot
```

O script roda os testes, o teste netem neste host e uma execução S0 fora da bateria (em
`data/raw/_pilot/`), confere automaticamente o piloto e estima o disco necessário (× 24).

- [x] Anotar no `EXECUTION_LOG.md` (seção 4): testes, netem, espaço em disco, duração.
- [x] **Abrir manualmente** os arquivos do piloto (`data/raw/_pilot/<run_id>/`):
  - [x] `manifest.json` completo (cenário, sementes, parâmetros, netem, interfaces, versões,
        hardware, commit, `converged: true`);
  - [x] `client/client.sqlite`: 1000 eventos, todos `ACKED`. Um visualizador de SQLite ajuda,
        ex.: DB Browser for SQLite;
  - [x] `client/requests.jsonl` e `server/server_requests.jsonl` não vazios e com o mesmo
        número de linhas (em S0 não há falhas);
  - [x] `network_events.jsonl`: em S0, só `reset`, `t0` e `final` (D-020, item 1).
- [x] Rodar a análise **só no piloto**, no PowerShell do Windows (que tem numpy/scipy/matplotlib):
  ```powershell
  python analysis/metrics.py --in data/raw/_pilot --out data/pilot_processed
  ```
  e conferir em `data/pilot_processed/metrics_per_run.csv`: R1 = 100, R2 = 0, C1 = C3 = C4 = 0.
- [ ] Se qualquer item falhar: **parar** e seguir a seção 6 do plano.

### A.3 Rodada (seção 3.3)

```bash
bash experiments/preliminary.sh round      # S0,S2,S4,S6,S7,S9 × 3 + 6 aquecimentos
```

- [x] Rodar de uma vez. Estimativa pelas execuções de aceite: ~2 min por execução nos cenários
      curtos e ~11–12 min por execução de S6 (600 s offline), **~1h30 no total**.
- [x] Anotar início e fim (ficam também em `data/raw/preliminary_<timestamp>.log`).
- [ ] **Se for interrompida:** manter as execuções concluídas e mover para
      `data/raw/_invalid/` (com uma nota `NOTA.md` explicando) a execução que estava em
      andamento. Depois retomar **só o que falta, com novas sementes**, por cenário, ex.:
      ```bash
      python3 experiments/run_experiment.py --scenarios S6 --reps 3 --reps-list 2,3 \
          --seed-tag retomada1 --no-warmup --out data/raw
      ```
      (use `--no-warmup` só se o aquecimento daquele cenário já tiver rodado). Registrar a
      interrupção no `EXECUTION_LOG.md`, seção 7.

### A.4 Processamento (seção 3.4), no PowerShell do Windows

```powershell
python analysis/metrics.py --in data/raw --out data/processed
python analysis/plots.py   --in data/processed --raw data/raw --out data/figures
python analysis/checks.py  --raw data/raw --processed data/processed
```

`stats.py` **não** roda nesta rodada (n = 3: resultados apenas descritivos).

- [x] Ler `data/processed/checks_report.md` e agir conforme a seção 6 do plano:
  - **FALHOU em 4.2 (garantias):** defeito ou achado. Parar a análise, investigar os logs da
    execução, corrigir o código, registrar em `DECISIONS.md`, mover **todas** as execuções do
    commit anterior para `data/raw/_invalid/<commit>/` e repetir a rodada inteira;
  - **FALHOU em 4.1 (integridade):** investigar (execução faltando, commit diferente etc.);
  - **NÃO CONFIRMADA em 4.3:** não é erro; registrar para a orientação com os valores observados;
  - execução que não convergiu: é resultado (R3), não erro; registrar o motivo aparente.
- [x] Preencher o `EXECUTION_LOG.md` (seções 5 a 9) a partir do `checks_report.md`.
- [x] Commitar `EXECUTION_LOG.md` (os dados em `data/` não vão para o Git; ver E.2).

> **Feito em 2026-10-31** (A.1–A.4): piloto às 20:08; rodada do plano 20:10–21:28; rodada
> complementar (S1, S3, S5, S8, S10; D-021) 21:28–22:08; processamento, `checks_report.md`,
> `EXECUTION_LOG.md` e tabelas LaTeX (`python analysis/latex_tables.py` → `data/tables/`).

### A.5 Levar para a conversa de orientação (seção 8 do plano)

- [ ] `data/processed/summary_preliminary.csv`
- [ ] `data/processed/checks_report.md`
- [ ] figuras de `data/figures/` (`d1_median_points`, `d2_points`, `d3_points`, `queue_S6`, `queue_S8`),
      tabelas de `data/tables/` e diagramas de `docs/` (`arquitetura`, `sequencia`)
- [ ] `EXECUTION_LOG.md`
- [ ] `DECISIONS.md`

---

## B. Decisões ainda abertas [CONFIRMAR]

- [x] **D-017: métricas testadas e correção** (decidido em 2026-11-01): R4, R5, D1 mediana,
      D1 p95, D2, D5, D6 e C2; Holm por família (confiabilidade 20, desempenho 50, consistência 10).
      Implementado em `stats.py`; regra escrita na seção 4.9 da Metodologia (Overleaf).
- [ ] **Critérios operacionais do `checks.py` (D-020, item 7).** "S2/S4 maior que S0" = o menor
      valor do cenário é maior que o maior valor de S0; "D6 muito menor que 1000" = D6 ≤ 100.
      Confirmar ou trocar (as constantes estão no início de `analysis/checks.py`).
- [x] **S7: tratamento decidido (D-022):** achado; previsão original mantida e relatada como
      refutada; cenário não muda; expectativas revisadas (S7 R5 = 0, S8 R5 > 0) registradas e
      verificadas no `checks.py`.
- [ ] **Opcional: confirmar a explicação pelo TCP** com uma execução diagnóstica do S7 fora do
      conjunto de dados (`tcpdump` no container do cliente, ou `nstat` antes e depois). Sem isso,
      o texto diz "explicação compatível com os tempos medidos".
- [ ] **Fonte do RTO mínimo de 200 ms do Linux** (documentação ou código do kernel), se o
      texto citar os valores; a dobra do RTO está no RFC 6298.
- [ ] Revisar e dar aceite geral às demais decisões do `DECISIONS.md` que mexem no desenho:
      D-008 (t0 absoluto, 3 s após o comando), D-009 (timeout por operação de socket), D-010
      (resposta com `REJECTED_GAP` não conta como falha), D-015 (cálculo de t_ref e do limite),
      D-016 (definições operacionais de D2, D3, D6 e C1).

---

## C. Ajustes no texto do TCC (Metodologia e Resultados)

- [ ] **S7 no texto (D-022):** relatar a previsão original ("R5 > 0") e que não se confirmou;
      apresentar como achado (interrupção mais curta que o timeout → latência em D1, não falha em
      R5), com o contraste S7 × S8; ameaças à validade de construto e externa.
- [x] **Seção 4.9 da Metodologia:** métricas testadas, famílias, hipóteses H0/H1 genéricas, regra
      de empates e limitação do controle por família (D-017).

- [ ] **Ciclo de vida do evento** (D-021): "criado → salvo localmente → enviado → confirmado →
      removível; mantido durante os experimentos para auditoria".
- [ ] **D2 nos cenários com ciclos** (EXECUTION_LOG, seção 10, item 3): em S8 e S10 a geração termina
      dentro de uma fase offline, e D2 inclui ~20 s de espera até a rede voltar.
- [ ] **Tempo de execução:** medido 1 h 57 min para 44 execuções; projeção de ~5,3 h para o Ciclo 3
      (a Metodologia estimava 8–10 h).
- [ ] **Tabelas LaTeX** (`data/tables/*.tex`): exigem `\usepackage{booktabs}` e `\usepackage{graphicx}`.
      Cada uma traz "Fonte: Elaborado pelo autor." e a nota; desempenho em duas tabelas
      (`tab:desempenho-latencia`: D1; `tab:desempenho-recuperacao`: D2–D6). Gere de novo com
      `latex_tables.py` em vez de editar à mão no Overleaf, para não perder ajustes.

- [ ] **Jitter do netem:** "60 ms ± 12 ms" com `distribution normal` significa média de 60 ms e
      parâmetro de variação de 12 ms, não um intervalo fechado (plano do protótipo, seção 6.2).
      O mesmo vale para "500 ms ± 100 ms".
- [ ] **Tamanho do payload** (D-007/D-019): fixo por campo, não por tipo de operação. CREATE =
      172 bytes; DELETE = 2; UPDATE = 76 (`title`), 82 (`description`) ou 16 (`value`).
- [ ] **Ambiente real:** Windows 11 + WSL2 (Ubuntu 24.04, kernel 6.6.114.1-microsoft-standard-WSL2),
      Docker Engine nativo no WSL2, cliente e servidor no mesmo host, i7-12700F (12 núcleos, 20 threads), 32 GB no host,
      dos quais o WSL2 enxerga 16 GB (limite padrão do WSL2, metade da memória). Se a
      Metodologia fala em "host Linux", ajustar ou explicar que o WSL2 é uma VM Linux leve.
- [ ] **Relógio compartilhado:** orquestrador e containers no mesmo kernel (WSL2), verificado
      a cada execução (D-013).
- [ ] **Latência do `docker exec`** nas mudanças de rede: ~95–250 ms medidos (valor final da
      rodada no `EXECUTION_LOG.md`). Mencionar como limitação em S7, S8 e S10 (janelas de 5 s e
      30 s).
- [ ] **D1 sem degradação (~18 ms em S0)** vem principalmente das gravações duráveis do SQLite
      (fsync por commit no cliente e no servidor), não da rede (RTT ≈ 0,1 ms). Explicar ao
      interpretar D1.
- [ ] **TCP_NODELAY** (D-011): mencionar que o servidor envia a resposta num único segmento, sem
      Nagle. Sem isso, havia ~40 ms artificiais por requisição.
- [ ] **Timeout T = 10 s** vale por operação de socket (D-009).
- [ ] **S9:** a taxa é uma *probabilidade* de descarte de 0,10 por requisição (sorteio com
      semente); a proporção realizada varia (7,5% na execução de aceite). Descrever a taxa
      realizada por execução nos resultados.
- [ ] **Resultados do Ciclo 2:** chamar de "resultados preliminares descritivos", sem falar em
      diferença significativa (n = 3; menor p possível = 0,10).
- [ ] Se o texto citar `docker compose`: o orquestrador usa a CLI do docker (D-014).
- [ ] Passo 7 da orientação: texto dos resultados preliminares e atualização do LaTeX (figuras
      em PDF de `data/figures/`).

---

## D. Bateria completa (Ciclo 3, fase 9)

- [ ] Passo 8 da orientação: conferir a cadeia e as pendências do Ciclo 3.
- [ ] Corrigir o que a rodada preliminar revelar. **Toda** correção de código: registrar em
      `DECISIONS.md`, commitar e não misturar execuções de commits diferentes.
- [ ] Resolver D-017 (seção B).
- [ ] **Opcional, a confirmar com o orientador (D-021):** "S6 com volumes variados", com a
      mesma desconexão de 600 s e N = 300, 1000 e 3000, para isolar o efeito do volume acumulado.
      O orquestrador já aceita `--n-events`; falta registrar o N no cenário e no manifesto e
      ajustar a Metodologia. São ~11–12 min por execução.
- [ ] Recalcular o tempo total com as durações reais da rodada preliminar. Estimativa grosseira
      pelas execuções de aceite: 11 cenários × 11 execuções, com S6 ~11–12 min e os demais
      ~2–4 min cada, **~6–8 h**. A Metodologia fala em 8–10 h; atualizar o texto com o valor medido.
- [ ] Decidir se a bateria roda de uma vez (madrugada) ou em blocos por cenário. As duas formas
      são suportadas, desde que tudo seja feito com o **mesmo commit**.
- [ ] Rodar: `python3 experiments/run_experiment.py --scenarios S0,S1,S2,S3,S4,S5,S6,S7,S8,S9,S10 --reps 10 --out data/raw_ciclo3`
      (pasta separada da rodada preliminar).
- [ ] Processar: `metrics.py`, `checks.py --scenarios S0,...,S10 --reps 10`, **`stats.py`**
      (Mann–Whitney + Holm) e `plots.py` (com n = 10 também sai o boxplot de D1, e a série da
      fila de S8).
- [ ] Conferir `alerts.txt` e `checks_report.md`; registrar tudo num `EXECUTION_LOG` do Ciclo 3.
- [ ] Atualizar o texto: tabelas por cenário, comparações com S0 (diferença de medianas, p
      ajustado), número de comparações, figuras.

---

## E. Encerramento do estudo

- [ ] **Congelar o código:** criar uma tag Git no commit usado na bateria completa (ex.:
      `git tag ciclo3-final <hash>`) e fazer o merge de `feat/prototipo` em `main` (ou PR) quando
      o autor aprovar.
- [ ] **Preservar os dados:** `data/` não vai para o Git (`.gitignore`). Compactar `data/raw/`,
      `data/processed/` e `data/figures/` de cada ciclo, guardar em pelo menos dois lugares
      (ex.: Google Drive + HD externo) e registrar um checksum (`sha256sum dados.zip`). Se o
      curso pedir, depositar num repositório de dados (ex.: Zenodo) e citar no TCC.
- [ ] Separar os dados de teste do protótipo (`data/smoke*`, `data/acceptance*`,
      `data/netem_check*.json`): não são resultados. Arquivar à parte ou apagar depois da defesa.
- [ ] Ameaças à validade no texto: um único host e um único cliente; WSL2 em vez de Linux
      nativo; netem só na saída de cada container; latência do `docker exec`; tamanho
      variável do UPDATE; armazenamento durável influenciando D1.
- [ ] README final: revisar instruções e o mapa arquivos → métricas para o estado final.
- [ ] Revisão final pelo orientador e defesa.
