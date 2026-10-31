"""Orquestrador dos experimentos (plano, seção 6.4). Biblioteca padrão apenas.

    python3 experiments/run_experiment.py --scenarios S0,S2 --reps 3 --out data/raw

Para cada cenário: uma execução de aquecimento (em <out>/_warmup/, excluída da análise) e
depois as `reps` execuções. Deve rodar num host Linux que compartilhe o kernel com os
containers (no Windows: dentro do WSL2; ver DECISIONS.md, D-013).
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dockerctl as dc  # noqa: E402

SCENARIOS_FILE = Path(__file__).resolve().parent / "scenarios.json"

# Parâmetros fixos (plano, seção 3). N e taxa ficam aqui porque o orquestrador calcula prazos.
N_EVENTS = 1000
RATE_PER_S = 10.0
CONVERGENCE_LIMIT_S = 15 * 60
START_LEAD_S = 3.0          # t0 = instante do comando + 3 s (D-008)
POLL_S = 1.0
CLIENT_ID = "client-1"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def derive_seed(master, scenario, rep, role):
    raw = f"{master}|{scenario}|{rep}|{role}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def load_scenarios():
    data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    return data["offline_spec"], data["scenarios"]


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def cmd_out(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"erro: {exc!r}"


def host_info():
    info = {"platform": platform.platform(), "uname_r": platform.release(),
            "python_orchestrator": sys.version}
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        models = [line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                  if line.startswith("model name")]
        info["cpu_model"] = models[0] if models else None
        info["cpu_count"] = len(models)
        mem = [line for line in Path("/proc/meminfo").read_text().splitlines()
               if line.startswith("MemTotal")]
        info["mem_total"] = mem[0].split(":", 1)[1].strip() if mem else None
    except OSError:
        info["cpu_model"] = platform.processor()
        info["cpu_count"] = os.cpu_count()
    return info


def static_info():
    """Informações que não mudam dentro de uma bateria (plano, seção 6.5)."""
    root = str(dc.ROOT)
    return {
        "git_commit": cmd_out(["git", "-C", root, "rev-parse", "HEAD"]),
        "git_dirty": bool(cmd_out(["git", "-C", root, "status", "--porcelain"])),
        "docker_version": cmd_out(["docker", "version", "--format",
                                   "client {{.Client.Version}} / server {{.Server.Version}}"]),
        "host": host_info(),
    }


def container_info():
    return {
        "python_version": {c: dc.dexec(c, "python", "--version").stdout.strip() for c in dc.CONTAINERS},
        "tc_version": dc.dexec(dc.CLIENT, "tc", "-V", check=False).stdout.strip(),
    }


def wait_health(timeout_s=60):
    code = ("import urllib.request;"
            "print(urllib.request.urlopen('http://server:8080/health', timeout=2).status)")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        p = dc.dexec(dc.CLIENT, "python", "-c", code, check=False)
        if p.returncode == 0 and p.stdout.strip() == "200":
            return
        time.sleep(0.5)
    raise dc.CommandError("servidor não respondeu a GET /health")


def read_container_json(container, path):
    p = dc.dexec(container, "cat", path, check=False)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def fetch_server_hashes():
    code = ("import urllib.request, sys;"
            "sys.stdout.write(urllib.request.urlopen('http://server:8080/state/hashes', timeout=30)"
            ".read().decode())")
    return json.loads(dc.dexec(dc.CLIENT, "python", "-c", code).stdout)


class NetworkDriver(threading.Thread):
    """Conduz as mudanças de rede do cenário relativas a t0 (S5, S6, S7, S8, S10)."""

    def __init__(self, net, scenario, offline_spec, t0_ns, stop_event):
        super().__init__(name="network", daemon=True)
        self.net, self.sc, self.offline = net, scenario, offline_spec
        self.t0_ns, self.stop = t0_ns, stop_event
        self.restore_ns = None  # instante de restauração (S5/S6), para t_ref
        self.error = None

    def _wait_until(self, offset_s):
        delay = (self.t0_ns + int(offset_s * 1e9) - time.time_ns()) / 1e9
        return not (delay > 0 and self.stop.wait(delay)) and not self.stop.is_set()

    def run(self):
        try:
            if self.sc["type"] == "initial_outage":
                if self._wait_until(self.sc["outage_s"]):
                    rec = self.net.set(self.sc["online"], "restore")
                    self.restore_ns = rec["t_applied_ns"]
                    log(f"rede restaurada em t0+{(self.restore_ns - self.t0_ns) / 1e9:.3f} s")
            elif self.sc["type"] == "cycles":
                t, online = 0.0, True
                while True:
                    t += self.sc["online_s"] if online else self.sc["offline_s"]
                    if not self._wait_until(t):
                        break
                    online = not online
                    self.net.set(self.sc["online"] if online else self.offline,
                                 "online" if online else "offline")
        except Exception as exc:  # registrado no manifesto; a execução é marcada como inválida
            self.error = repr(exc)


def initial_spec(scenario, offline_spec):
    return offline_spec if scenario["type"] == "initial_outage" else scenario["online"]


def run_once(scenario_id, scenario, offline_spec, rep, is_warmup, master_seed, run_dir,
             static, n_events, allow_clock_mismatch):
    run_dir.mkdir(parents=True, exist_ok=False)
    seeds = {role: derive_seed(master_seed, scenario_id, "warmup" if is_warmup else rep, role)
             for role in ("client", "jitter", "server")}
    drop_rate = scenario.get("drop_response_rate", 0.0)
    timings = {"run_started_ns": time.time_ns()}

    # 1. containers limpos
    dc.up(drop_response_rate=drop_rate, server_seed=seeds["server"])
    wait_health()
    interfaces = {c: dc.detect_interface(c) for c in dc.CONTAINERS}
    clock = {c: dc.container_clock_offset_ns(c) for c in dc.CONTAINERS}
    if not all(v["same_clock"] for v in clock.values()) and not allow_clock_mismatch:
        raise dc.CommandError(f"relógio do orquestrador difere do dos containers: {clock} (D-013)")

    manifest = {
        "run_id": run_dir.name, "scenario": scenario_id, "scenario_definition": scenario,
        "offline_spec": offline_spec, "repetition": None if is_warmup else rep,
        "is_warmup": is_warmup, "master_seed": master_seed, "seeds": seeds,
        "parameters": {
            "clients": 1, "concurrent_requests": 1, "n_events": n_events, "rate_per_s": RATE_PER_S,
            "convergence_limit_s": CONVERGENCE_LIMIT_S, "drop_response_rate": drop_rate,
            "netem_jitter_distribution": "normal", "start_lead_s": START_LEAD_S,
        },
        "interfaces": interfaces, "clock_offset": clock, "converged": None,
        **static, **container_info(),
    }
    write_json(run_dir / "manifest.json", manifest)

    net = dc.NetworkController(interfaces, run_dir / "network_events.jsonl")
    stop = threading.Event()
    driver = None
    client_proc = None
    exit_code, killed = None, False
    try:
        # 4. condição inicial e t0
        net.clear("reset")
        spec0 = initial_spec(scenario, offline_spec)
        if spec0 is not None:
            net.set(spec0, "initial")
        t0_ns = time.time_ns() + int(START_LEAD_S * 1e9)
        timings["t0_ns"] = t0_ns

        # 5. cliente
        client_cmd = ["docker", "exec", dc.CLIENT, "python", "-m", "sync_client.main",
                      "--server-host", "server", "--server-port", "8080",
                      "--client-id", CLIENT_ID, "--n-events", str(n_events),
                      "--seed", str(seeds["client"]), "--jitter-seed", str(seeds["jitter"]),
                      "--out-dir", "/data", "--start-at-ns", str(t0_ns)]
        manifest["client_command"] = client_cmd
        stdout = open(run_dir / "client_stdout.log", "w", encoding="utf-8")
        client_proc = subprocess.Popen(client_cmd, stdout=stdout, stderr=subprocess.STDOUT)

        # 6. mudanças de rede
        driver = NetworkDriver(net, scenario, offline_spec, t0_ns, stop)
        driver.start()

        # 7. aguarda convergência ou o limite de 15 min após t_ref
        gen_expected_ns = t0_ns + int(n_events / RATE_PER_S * 1e9)
        outage_s = scenario.get("outage_s", 0)
        hard_cap_ns = (t0_ns + int((n_events / RATE_PER_S + outage_s + CONVERGENCE_LIMIT_S + 120) * 1e9))
        last_created_ns, deadline_ns = None, None
        while client_proc.poll() is None:
            time.sleep(POLL_S)
            now = time.time_ns()
            if last_created_ns is None and now > gen_expected_ns:
                gen = read_container_json(dc.CLIENT, "/data/generation_done.json")
                if gen:
                    last_created_ns = gen["last_created_at_ns"] or t0_ns
            if deadline_ns is None and last_created_ns is not None:
                if scenario["type"] != "initial_outage":
                    deadline_ns = last_created_ns + CONVERGENCE_LIMIT_S * 10**9
                elif driver.restore_ns is not None:
                    deadline_ns = max(last_created_ns, driver.restore_ns) + CONVERGENCE_LIMIT_S * 10**9
            limit = deadline_ns if deadline_ns is not None else hard_cap_ns
            if now > min(limit, hard_cap_ns) and not killed:
                log("limite de convergência atingido: encerrando o cliente (SIGTERM)")
                dc.dexec(dc.CLIENT, "sh", "-c", "kill -TERM $(cat /data/client.pid)", check=False)
                killed = True
                timings["client_killed_ns"] = time.time_ns()
        exit_code = client_proc.returncode
        stdout.close()
        timings["client_exited_ns"] = time.time_ns()
        timings["deadline_ns"] = deadline_ns
    finally:
        stop.set()
        if driver is not None:
            driver.join(30)
        if client_proc is not None and client_proc.poll() is None:
            client_proc.kill()
        # 8. remove o netem dos dois containers
        net.clear("final")

    # 9. coleta: hashes do servidor, parada limpa do servidor e cópia dos arquivos
    write_json(run_dir / "server_state_hashes.json", fetch_server_hashes())
    dc.run(["docker", "stop", "-t", "20", dc.SERVER])
    for container, sub in ((dc.CLIENT, "client"), (dc.SERVER, "server")):
        (run_dir / sub).mkdir()
        dc.run(["docker", "cp", f"{container}:/data/.", str(run_dir / sub)])
    timings["run_finished_ns"] = time.time_ns()

    client_done = (run_dir / "client" / "client_done.json").exists()
    client_info = json.loads((run_dir / "client" / "client_info.json").read_text(encoding="utf-8"))
    manifest.update({
        "converged": bool(exit_code == 0 and client_done and not killed),
        "client_exit_code": exit_code,
        "client_killed_by_limit": killed,
        "network_driver_error": driver.error if driver else None,
        "restore_ns": driver.restore_ns if driver else None,
        "netem_commands": sorted(net.commands_used),
        "client_parameters": client_info["config"],
        "operation_counts": client_info["operation_counts"],
        "timings": timings,
        "wall_time_s": (timings["run_finished_ns"] - timings["run_started_ns"]) / 1e9,
    })
    write_json(run_dir / "manifest.json", manifest)
    # 10. derruba os containers
    dc.down()
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", required=True, help="lista separada por vírgula, ex.: S0,S2")
    ap.add_argument("--reps", type=int, required=True)
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--master-seed", type=int, default=20261031)
    ap.add_argument("--no-warmup", action="store_true", help="só para testes do protótipo")
    ap.add_argument("--n-events", type=int, default=N_EVENTS,
                    help="só para testes do protótipo; a metodologia fixa N = 1000")
    ap.add_argument("--allow-clock-mismatch", action="store_true", help="só para depuração (D-013)")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()

    offline_spec, scenarios = load_scenarios()
    ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [s for s in ids if s not in scenarios]
    if unknown:
        ap.error(f"cenários desconhecidos: {unknown}")
    if args.n_events != N_EVENTS:
        log(f"AVISO: n_events = {args.n_events} difere do parâmetro fixo N = {N_EVENTS}")
    if platform.system() != "Linux":
        log("AVISO: o orquestrador não está num host Linux (ver DECISIONS.md, D-013)")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if not args.no_build:
        log("construindo a imagem...")
        dc.build()
    static = static_info()
    if static["git_dirty"]:
        log("AVISO: há alterações não commitadas; o commit do manifesto não descreve o código exato")

    battery = {"started_at": datetime.now().isoformat(), "args": vars(args), "runs": []}
    battery_file = out / f"battery_{stamp}.json"
    t_start = time.monotonic()
    for sid in ids:
        plan = ([] if args.no_warmup else [(0, True)]) + [(r, False) for r in range(1, args.reps + 1)]
        for rep, is_warmup in plan:
            run_id = f"{sid}_{'warmup' if is_warmup else f'r{rep:02d}'}_{stamp}"
            run_dir = (out / "_warmup" if is_warmup else out) / run_id
            log(f"{run_id}: iniciando")
            t = time.monotonic()
            entry = {"run_id": run_id, "scenario": sid, "is_warmup": is_warmup, "dir": str(run_dir)}
            try:
                m = run_once(sid, scenarios[sid], offline_spec, rep, is_warmup, args.master_seed,
                             run_dir, static, args.n_events, args.allow_clock_mismatch)
                entry.update(converged=m["converged"], wall_time_s=m["wall_time_s"])
                log(f"{run_id}: converged={m['converged']} em {time.monotonic() - t:.0f} s")
            except Exception as exc:
                entry.update(error=repr(exc))
                log(f"{run_id}: ERRO {exc!r}")
                dc.down()
            battery["runs"].append(entry)
            battery["elapsed_s"] = time.monotonic() - t_start
            write_json(battery_file, battery)
    battery["finished_at"] = datetime.now().isoformat()
    write_json(battery_file, battery)
    log(f"bateria concluída em {battery['elapsed_s'] / 60:.1f} min; resumo em {battery_file}")
    return 0 if all("error" not in r for r in battery["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
