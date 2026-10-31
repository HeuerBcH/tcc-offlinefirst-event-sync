"""Transporte HTTP persistente com contagem de bytes no nível do socket (plano, seção 4.5)."""
import http.client
import io
import json
import socket
from dataclasses import dataclass


class ByteCounter:
    def __init__(self):
        self.sent = 0
        self.recv = 0

    def reset(self):
        self.sent = 0
        self.recv = 0


class CountingSocket:
    """Envolve o socket da conexão e conta todo byte enviado e recebido.

    makefile() cria o SocketIO sobre o próprio wrapper, de modo que a leitura da resposta
    (linha de status, cabeçalhos e corpo) passa por recv_into() e é contada.
    """

    def __init__(self, sock, counter):
        self._sock = sock
        self._counter = counter

    def send(self, data, *args):
        n = self._sock.send(data, *args)
        self._counter.sent += n
        return n

    def sendall(self, data, *args):
        self._sock.sendall(data, *args)
        self._counter.sent += memoryview(data).nbytes

    def recv(self, bufsize, *args):
        data = self._sock.recv(bufsize, *args)
        self._counter.recv += len(data)
        return data

    def recv_into(self, buffer, nbytes=0, *args):
        n = self._sock.recv_into(buffer, nbytes, *args)
        self._counter.recv += n
        return n

    def makefile(self, mode="r", buffering=None, **_kwargs):
        if "b" not in mode or "w" in mode:
            raise ValueError("CountingSocket.makefile só suporta leitura binária")
        raw = socket.SocketIO(self, "rb")
        if buffering is None or buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            return raw
        return io.BufferedReader(raw, buffering)

    def _decref_socketios(self):
        # O fechamento real é feito por HTTPConnection.close() -> close().
        pass

    def close(self):
        self._sock.close()

    def __getattr__(self, name):
        return getattr(self._sock, name)


class CountingHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, timeout, counter):
        super().__init__(host, port, timeout=timeout)
        self.counter = counter

    def connect(self):
        super().connect()
        self.sock = CountingSocket(self.sock, self.counter)


@dataclass
class TransportResult:
    outcome: str  # ok | timeout | conn_error | remote_disconnected | http_error
    http_status: object
    body: object  # JSON decodificado quando outcome == "ok"
    bytes_sent: int
    bytes_recv: int
    error: object = None


class Transport:
    """Conexão keep-alive; qualquer falha fecha a conexão e a próxima tentativa abre outra."""

    def __init__(self, host, port, timeout_s):
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.counter = ByteCounter()
        self._conn = None

    def _connection(self):
        if self._conn is None:
            self._conn = CountingHTTPConnection(self.host, self.port, self.timeout_s, self.counter)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def post_json(self, path, obj):
        body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.counter.reset()
        status, outcome, data, error = None, "ok", None, None
        try:
            conn = self._connection()
            conn.request("POST", path, body, {"Content-Type": "application/json"})
            resp = conn.getresponse()
            status = resp.status
            raw = resp.read()
            if status != 200:
                outcome, error = "http_error", f"HTTP {status}"
            else:
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                        raise ValueError("resposta sem lista 'results'")
                except ValueError as exc:
                    outcome, error = "http_error", f"JSON inválido: {exc}"
            if resp.will_close:
                self.close()
        except (TimeoutError, socket.timeout) as exc:
            outcome, error = "timeout", repr(exc)
        except http.client.RemoteDisconnected as exc:
            outcome, error = "remote_disconnected", repr(exc)
        except http.client.HTTPException as exc:
            outcome, error = "http_error", repr(exc)
        except OSError as exc:  # ConnectionError e demais erros de socket
            outcome, error = "conn_error", repr(exc)
        if outcome != "ok":
            self.close()
            data = None
        return TransportResult(outcome, status, data, self.counter.sent, self.counter.recv, error)
