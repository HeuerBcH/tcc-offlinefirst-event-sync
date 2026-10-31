"""Parâmetros do cliente (plano, seção 3), por argumento de linha de comando ou variável de ambiente.

Os valores padrão são os parâmetros fixos da metodologia e os padrões de projeto de DECISIONS.md.
"""
import argparse
import os
from dataclasses import asdict, dataclass, fields


@dataclass
class ClientConfig:
    server_host: str = "server"
    server_port: int = 8080
    client_id: str = "client-1"
    # Parâmetros fixos (metodologia 4.5 e especificação, seção 8)
    n_events: int = 1000
    rate_per_s: float = 10.0
    batch_size: int = 50
    request_timeout_s: float = 10.0
    backoff_base_s: float = 0.5
    backoff_max_s: float = 30.0
    # Parâmetros de projeto (DECISIONS.md, D-002)
    mix_create: float = 0.30
    mix_update: float = 0.60
    mix_delete: float = 0.10
    text_field_len: int = 64
    queue_limit: int = 10000
    idle_check_s: float = 1.0
    # Execução
    seed: int = 1
    jitter_seed: int = 2
    out_dir: str = "/data"
    start_at_ns: int = 0  # 0 = começa imediatamente

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_args(cls, argv=None, env=None):
        env = os.environ if env is None else env
        parser = argparse.ArgumentParser(description="Cliente de sincronização (uma execução).")
        for f in fields(cls):
            cast = type(f.default)
            value = env.get("SYNC_" + f.name.upper())
            parser.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=cast,
                                default=cast(value) if value is not None else f.default)
        return cls(**vars(parser.parse_args(argv)))
