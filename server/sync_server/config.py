"""Parâmetros do servidor, lidos de variáveis de ambiente."""
import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: str = "/data"
    drop_response_rate: float = 0.0
    server_seed: int = 0

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            host=env.get("SYNC_HOST", cls.host),
            port=int(env.get("SYNC_PORT", cls.port)),
            data_dir=env.get("SYNC_DATA_DIR", cls.data_dir),
            drop_response_rate=float(env.get("DROP_RESPONSE_RATE", cls.drop_response_rate)),
            server_seed=int(env.get("SERVER_SEED", cls.server_seed)),
        )
