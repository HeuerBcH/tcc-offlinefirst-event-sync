"""Controle dos containers e do netem a partir do host (biblioteca padrão apenas).

Usado por run_experiment.py e netem_check.py.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "tcc-sync:latest"
NETWORK = "tccsync_syncnet"
CLIENT = "tcc-client"
SERVER = "tcc-server"
CONTAINERS = (CLIENT, SERVER)


class CommandError(RuntimeError):
    pass


def run(cmd, check=True, input=None, timeout=None, env=None):
    proc = subprocess.run(cmd, input=input, capture_output=True, text=True, timeout=timeout,
                          env=env, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise CommandError(f"{' '.join(cmd)} -> {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc


# O ambiente é montado com a CLI do docker, sem depender do plugin compose (ausente no
# Docker Engine nativo do WSL). Mesmos parâmetros de docker/docker-compose.yml (D-014).

def build():
    run(["docker", "build", "-t", IMAGE, "-f", str(ROOT / "docker" / "Dockerfile"), str(ROOT)],
        timeout=1800)


def down():
    run(["docker", "rm", "-f", *CONTAINERS], check=False)
    run(["docker", "network", "rm", NETWORK], check=False)


def up(drop_response_rate=0.0, server_seed=0):
    """Recria rede e containers (bancos vazios)."""
    down()
    run(["docker", "network", "create", "--driver", "bridge", NETWORK])
    run(["docker", "run", "-d", "--name", SERVER, "--network", NETWORK, "--network-alias", "server",
         "--cap-add", "NET_ADMIN",
         "-e", "SYNC_DATA_DIR=/data", "-e", "SYNC_PORT=8080",
         "-e", f"DROP_RESPONSE_RATE={drop_response_rate}", "-e", f"SERVER_SEED={server_seed}",
         IMAGE, "python", "-m", "sync_server.main"])
    run(["docker", "run", "-d", "--init", "--name", CLIENT, "--network", NETWORK,
         "--network-alias", "client", "--cap-add", "NET_ADMIN", IMAGE, "sleep", "infinity"])


def dexec(container, *cmd, input=None, check=True, timeout=None, interactive=False):
    base = ["docker", "exec"] + (["-i"] if interactive or input is not None else [])
    return run(base + [container, *cmd], check=check, input=input, timeout=timeout)


def run_python(container, code, timeout=None):
    """Executa um script Python no container (via stdin) e devolve o JSON impresso no stdout."""
    proc = dexec(container, "python", "-", input=code, timeout=timeout)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def detect_interface(container):
    """Nome da interface de rede do container (sem assumir eth0)."""
    out = dexec(container, "ip", "-o", "link").stdout
    names = []
    for line in out.splitlines():
        name = line.split(":")[1].strip().split("@")[0]
        if name != "lo":
            names.append(name)
    if len(names) != 1:
        raise CommandError(f"{container}: esperada 1 interface além de lo, encontradas {names}")
    return names[0]


def netem_command(iface, spec):
    """spec None remove o netem; caso contrário, 'tc qdisc replace ... netem <spec>'."""
    if spec is None:
        return ["tc", "qdisc", "del", "dev", iface, "root"]
    return ["tc", "qdisc", "replace", "dev", iface, "root", "netem", *spec.split()]


def container_clock_offset_ns(container, samples=5):
    """Estima (relógio do container − relógio do host) pelo ponto médio de docker exec.

    A estimativa tem incerteza de metade da latência do exec. O teste decisivo é
    `same_clock`: em todas as amostras a leitura do container cai entre os instantes antes e
    depois do host, o que sempre vale quando o relógio é o mesmo.
    """
    best, same_clock = None, True
    for _ in range(samples):
        before = time.time_ns()
        inside = int(dexec(container, "python", "-c", "import time; print(time.time_ns())").stdout)
        after = time.time_ns()
        same_clock = same_clock and before <= inside <= after
        half = (after - before) // 2
        if best is None or half < best[1]:
            best = (inside - (before + half), half)
    return {"offset_ns": best[0], "uncertainty_ns": best[1], "same_clock": same_clock}


class NetworkController:
    """Aplica condições de rede nos dois containers e registra cada comando com instantes
    antes e depois (network_events.jsonl)."""

    def __init__(self, interfaces, log_path=None):
        self.interfaces = interfaces  # {container: iface}
        self.log_path = Path(log_path) if log_path else None
        self.records = []
        self.commands_used = set()

    def _apply_one(self, container, spec, label, out):
        cmd = netem_command(self.interfaces[container], spec)
        t_before = time.time_ns()
        proc = dexec(container, *cmd, check=False)
        t_after = time.time_ns()
        # Remover quando não há qdisc configurada não é erro.
        nothing_to_delete = spec is None and ("No such file" in proc.stderr
                                              or "handle of zero" in proc.stderr)
        ok = proc.returncode == 0 or nothing_to_delete
        out[container] = {
            "container": container, "label": label, "command": " ".join(cmd),
            "t_before_ns": t_before, "t_after_ns": t_after, "returncode": proc.returncode,
            "stderr": proc.stderr.strip(), "ok": ok,
        }

    def set(self, spec, label):
        """Aplica `spec` nos dois containers em paralelo. Devolve o registro da mudança.

        `t_applied_ns` = o mais tardio dos t_after: instante em que a condição vale nos dois
        sentidos com certeza.
        """
        out = {}
        threads = [threading.Thread(target=self._apply_one, args=(c, spec, label, out))
                   for c in self.interfaces]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        failed = [r for r in out.values() if not r["ok"]]
        if failed:
            raise CommandError(f"falha ao aplicar netem '{spec}': {failed}")
        record = {
            "label": label, "spec": spec,
            "t_first_before_ns": min(r["t_before_ns"] for r in out.values()),
            "t_applied_ns": max(r["t_after_ns"] for r in out.values()),
            "commands": [out[c] for c in sorted(out)],
        }
        for r in out.values():
            self.commands_used.add(r["command"])
        self.records.append(record)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        return record

    def mark(self, label, t_ns, spec):
        """Registro sem comando tc (ex.: t0), com a condição de rede vigente."""
        record = {"label": label, "spec": spec, "marker": True, "t_first_before_ns": t_ns,
                  "t_applied_ns": t_ns, "commands": []}
        self.records.append(record)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        return record

    def clear(self, label="clear"):
        return self.set(None, label)
