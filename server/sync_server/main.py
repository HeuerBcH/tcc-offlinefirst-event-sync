"""Ponto de entrada do servidor: python -m sync_server.main"""
import signal
import sys
import threading

from .config import ServerConfig
from .handler import build_server


def main():
    config = ServerConfig.from_env()
    httpd = build_server(config)

    def on_signal(signum, frame):
        # shutdown() bloqueia até serve_forever terminar: precisa de outra thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    print(f"sync-server em {config.host}:{config.port}, dados em {config.data_dir}, "
          f"drop_response_rate={config.drop_response_rate}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        httpd.server_close()
        httpd.app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
