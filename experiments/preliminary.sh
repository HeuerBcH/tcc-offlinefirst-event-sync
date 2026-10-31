#!/usr/bin/env bash
# Rodada preliminar (Ciclo 2, Plano do Passo 6). Rodar DENTRO do WSL2 (Ubuntu), na raiz do repositório.
#
#   bash experiments/preliminary.sh pilot   # 3.1 + 3.2: testes, netem, execução piloto e estimativa de disco
#   bash experiments/preliminary.sh round   # 3.3: rodada S0,S2,S4,S6,S7,S9 × 3 + aquecimentos (~1h30)
#
# A análise (metrics.py, plots.py, checks.py) roda no Python com numpy/scipy/matplotlib
# (no Windows): ver PENDENCIAS.md.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=data/raw
SCENARIOS=S0,S2,S4,S6,S7,S9
REPS=3
STAMP=$(date +%Y%m%dT%H%M%S)

require_clean_git() {
    # Só o código conta; documentação (EXECUTION_LOG.md) pode mudar durante a rodada.
    if [ -n "$(git status --porcelain -- client server experiments docker analysis)" ]; then
        echo "ERRO: há alterações de código não commitadas. Commite antes (o commit vai para o manifesto)." >&2
        git status --short -- client server experiments docker analysis >&2
        exit 1
    fi
    echo "commit: $(git rev-parse HEAD)"
}

case "${1:-}" in
pilot)
    require_clean_git
    echo "== Testes do protótipo (seção 8 do plano do protótipo; análise é testada no Windows)"
    python3 -m unittest discover -s server/tests
    python3 -m unittest discover -s client/tests
    python3 -m unittest discover -s tests
    echo "== Teste netem funcional neste host"
    python3 experiments/netem_check.py --out "data/netem_check_${STAMP}.json"
    echo "== Execução piloto (S0, fora da bateria; vai para $OUT/_pilot/)"
    python3 experiments/run_experiment.py --scenarios S0 --reps 1 --pilot --out "$OUT"
    PILOT=$(ls -dt "$OUT"/_pilot/S0_pilot_* | head -1)
    echo "== Conferência automática do piloto: $PILOT"
    python3 - "$PILOT" <<'EOF'
import json, sqlite3, sys
from collections import Counter
d = sys.argv[1]
m = json.load(open(f"{d}/manifest.json"))
con = sqlite3.connect(f"{d}/client/client.sqlite")
n, acked = con.execute("SELECT COUNT(*), SUM(status='ACKED') FROM events").fetchone()
req = [json.loads(l) for l in open(f"{d}/client/requests.jsonl")]
sreq = [json.loads(l) for l in open(f"{d}/server/server_requests.jsonl")]
net = [json.loads(l)["label"] for l in open(f"{d}/network_events.jsonl")]
print(f"converged={m['converged']}  wall_time_s={m['wall_time_s']:.1f}")
print(f"client.sqlite: {n} eventos, {acked} ACKED")
print(f"requests.jsonl: {len(req)} linhas {dict(Counter(r['outcome'] for r in req))}; "
      f"server_requests.jsonl: {len(sreq)} linhas (esperado igual em S0)")
print(f"network_events.jsonl: {net} (S0: t0 + remoções de netem 'reset'/'final', sem netem aplicado)")
EOF
    SIZE_KB=$(du -sk "$PILOT" | cut -f1)
    echo "== Disco: piloto = ${SIZE_KB} KB; estimativa para 24 execuções = $((SIZE_KB * 24 / 1024)) MB"
    df -h "$OUT" | tail -1
    echo
    echo "Agora: abrir os arquivos do piloto manualmente e rodar a análise só nele (PENDENCIAS.md, etapa 3.2)."
    ;;
round)
    require_clean_git
    mkdir -p "$OUT"
    LOG="$OUT/preliminary_${STAMP}.log"
    echo "== Rodada preliminar: $SCENARIOS × $REPS + aquecimentos; log em $LOG"
    echo "início: $(date --iso-8601=seconds)  commit: $(git rev-parse HEAD)" | tee "$LOG"
    python3 experiments/run_experiment.py --scenarios "$SCENARIOS" --reps "$REPS" --out "$OUT" 2>&1 | tee -a "$LOG" \
        || echo "AVISO: run_experiment.py terminou com erro (ver battery_*.json)" | tee -a "$LOG"
    echo "fim: $(date --iso-8601=seconds)" | tee -a "$LOG"
    ;;
*)
    echo "uso: bash experiments/preliminary.sh {pilot|round}" >&2
    exit 2
    ;;
esac
