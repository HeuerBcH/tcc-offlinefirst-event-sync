"""Teste "netem funcional" (plano, seções 6.1 e 8). Deve passar antes de qualquer experimento.

    python experiments/netem_check.py [--out data/netem_check.json] [--keep-up]

Verifica, no host real:
  1. tc/netem disponível nos dois containers (módulo sch_netem no kernel);
  2. `delay 100ms` em cada sentido aumenta o tempo de uma requisição em ~200 ms;
  3. `loss 100%` faz a requisição terminar em timeout após T = 10 s
     (conexão nova e conexão keep-alive já aberta);
  4. ao remover o netem a comunicação volta.
Código de saída 0 = passou; 1 = falhou (o host não suporta o ambiente: PARAR).
"""
import argparse
import json
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dockerctl as dc  # noqa: E402

LATENCY_PROBE = """
import http.client, json, time
conn = http.client.HTTPConnection("server", 8080, timeout=10)
samples = []
for i in range({warmup} + {n}):
    t = time.perf_counter()
    conn.request("GET", "/health")
    conn.getresponse().read()
    if i >= {warmup}:
        samples.append((time.perf_counter() - t) * 1000)
conn.close()
print(json.dumps(samples))
"""

TIMEOUT_PROBE = """
import json, sys, time
sys.path.insert(0, "/app")
from sync_client.transport import Transport
tr = Transport("server", 8080, {timeout})
body = {{"client_id": "netem-check", "events": []}}
pre = None
if {established}:
    pre = tr.post_json("/sync/events", body).outcome   # abre a conexão keep-alive
    time.sleep({wait_s})                               # o host aplica loss 100% neste intervalo
t = time.monotonic()
r = tr.post_json("/sync/events", body)
print(json.dumps({{"pre": pre, "outcome": r.outcome, "elapsed_s": time.monotonic() - t,
                  "error": r.error}}))
"""


def wait_health(timeout_s=60):
    deadline = time.monotonic() + timeout_s
    code = ("import urllib.request, json;"
            "print(json.dumps(urllib.request.urlopen('http://server:8080/health', timeout=2).status))")
    while time.monotonic() < deadline:
        proc = dc.dexec(dc.CLIENT, "python", "-c", code, check=False)
        if proc.returncode == 0 and proc.stdout.strip() == "200":
            return True
        time.sleep(0.5)
    return False


def latency(n=30, warmup=3):
    samples = dc.run_python(dc.CLIENT, LATENCY_PROBE.format(n=n, warmup=warmup), timeout=120)
    return {"median_ms": statistics.median(samples), "min_ms": min(samples),
            "max_ms": max(samples), "n": len(samples)}


def versions():
    def out(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return f"erro: {exc!r}"
    return {
        "host_platform": platform.platform(),
        "docker_version": out(["docker", "version", "--format", "{{.Server.Version}}"]),
        "docker_kernel": out(["docker", "info", "--format", "{{.KernelVersion}}"]),
        "tc_version": dc.dexec(dc.CLIENT, "tc", "-V", check=False).stdout.strip(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(dc.ROOT / "data" / "netem_check.json"))
    ap.add_argument("--keep-up", action="store_true", help="não derrubar os containers no fim")
    args = ap.parse_args()

    report = {"started_at_ns": time.time_ns(), "checks": {}, "passed": False}
    checks = report["checks"]
    print("Subindo containers...")
    dc.build()
    dc.up()
    try:
        if not wait_health():
            raise dc.CommandError("servidor não respondeu a GET /health")
        report["versions"] = versions()
        interfaces = {c: dc.detect_interface(c) for c in dc.CONTAINERS}
        report["interfaces"] = interfaces
        print(f"Interfaces: {interfaces}")
        net = dc.NetworkController(interfaces)

        # 1. netem disponível
        try:
            rec = net.set("delay 0ms", "probe")
            checks["netem_available"] = {"ok": True, "exec_latency_ms": [
                (c["t_after_ns"] - c["t_before_ns"]) / 1e6 for c in rec["commands"]]}
            net.clear()
        except dc.CommandError as exc:
            checks["netem_available"] = {"ok": False, "error": str(exc)}
            raise

        # 2. delay 100 ms em cada sentido
        base = latency()
        net.set("delay 100ms", "delay-100ms")
        delayed = latency(n=15)
        net.clear()
        increase = delayed["median_ms"] - base["median_ms"]
        checks["delay_100ms"] = {"ok": 180 <= increase <= 260, "baseline": base,
                                 "delayed": delayed, "increase_ms": increase}
        print(f"delay: base {base['median_ms']:.1f} ms, com netem {delayed['median_ms']:.1f} ms "
              f"(+{increase:.1f} ms, esperado ~200)")

        # 3a. loss 100% com conexão nova
        net.set("loss 100%", "loss-100-fresh")
        fresh = dc.run_python(dc.CLIENT, TIMEOUT_PROBE.format(timeout=10, established=False, wait_s=0),
                              timeout=60)
        net.clear()
        checks["loss_100_fresh_connection"] = {
            "ok": fresh["outcome"] == "timeout" and 9.5 <= fresh["elapsed_s"] <= 11.5, **fresh}
        print(f"loss 100% (conexão nova): {fresh['outcome']} em {fresh['elapsed_s']:.2f} s")

        # 3b. loss 100% aplicado com a conexão keep-alive já aberta
        result = {}

        def probe():
            result.update(dc.run_python(
                dc.CLIENT, TIMEOUT_PROBE.format(timeout=10, established=True, wait_s=4), timeout=60))

        t = threading.Thread(target=probe)
        t.start()
        time.sleep(2)
        net.set("loss 100%", "loss-100-established")
        t.join()
        net.clear()
        checks["loss_100_established_connection"] = {
            "ok": result.get("pre") == "ok" and result.get("outcome") == "timeout"
            and 9.5 <= result.get("elapsed_s", 0) <= 11.5, **result}
        print(f"loss 100% (keep-alive): pré={result.get('pre')} {result.get('outcome')} "
              f"em {result.get('elapsed_s', 0):.2f} s")

        # 4. recuperação
        after = latency(n=5, warmup=1)
        checks["recovery"] = {"ok": after["median_ms"] < base["median_ms"] + 50, **after}

        report["netem_log"] = net.records
        report["clock_offset"] = {c: dc.container_clock_offset_ns(c) for c in dc.CONTAINERS}
        report["passed"] = all(c["ok"] for c in checks.values())
    except dc.CommandError as exc:
        report["error"] = str(exc)
        print(f"ERRO: {exc}")
    finally:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not args.keep_up:
            dc.down()
    print(json.dumps(checks, indent=2))
    print("PASSOU" if report["passed"] else "FALHOU: o host não suporta o ambiente. PARAR.")
    print(f"Relatório: {args.out}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
