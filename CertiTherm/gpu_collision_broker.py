"""Single-owner Unix-socket broker for the persistent CUDA LP process."""

from __future__ import annotations

from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
from typing import Optional


_LENGTHS = struct.Struct("<II")
_RESPONSE = struct.Struct("<I")


def request(socket_path: Path, input_path: Path, output_path: Path) -> None:
    paths = (str(input_path).encode(), str(output_path).encode())
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(_LENGTHS.pack(*(len(value) for value in paths)) + b"".join(paths))
        raw = _receive(client, _RESPONSE.size)
        size = _RESPONSE.unpack(raw)[0]
        response = _receive(client, size).decode(errors="replace")
    if response != "OK":
        raise RuntimeError("GPU collision broker failed: " + response[-800:])


def _receive(connection: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RuntimeError("GPU collision broker closed a partial message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class CollisionBroker:
    """Own one CUDA context while CPU method workers submit serial requests."""

    def __init__(self, solver: Path, device: int = 0) -> None:
        self.solver = Path(solver)
        self.device = device
        self.socket_path: Optional[Path] = None
        self._temporary = None
        self._server = None
        self._process = None
        self._thread = None
        self._stopping = threading.Event()

    def __enter__(self) -> "CollisionBroker":
        if not self.solver.is_file() or self.device < 0:
            raise ValueError("broker requires a CUDA solver and non-negative device")
        self._temporary = tempfile.TemporaryDirectory(prefix="certitherm-broker-")
        self.socket_path = Path(self._temporary.name) / "collision.sock"
        self._process = subprocess.Popen(
            [str(self.solver), "--server", str(self.device)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        self._server.listen()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _address = self._server.accept()
            except OSError:
                return
            with connection:
                try:
                    first, second = _LENGTHS.unpack(_receive(connection, _LENGTHS.size))
                    input_path = _receive(connection, first).decode()
                    output_path = _receive(connection, second).decode()
                    if not input_path and self._stopping.is_set():
                        return
                    self._process.stdin.write(input_path + "\n" + output_path + "\n")
                    self._process.stdin.flush()
                    response = self._process.stdout.readline().rstrip("\n")
                    if not response:
                        error = self._process.stderr.read()[-800:]
                        response = "ERROR persistent solver exited: " + error
                except Exception as exc:
                    response = f"ERROR broker: {type(exc).__name__}: {exc}"
                encoded = response.encode()
                connection.sendall(_RESPONSE.pack(len(encoded)) + encoded)

    def __exit__(self, _type, _value, _traceback) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.close()
        if self.socket_path is not None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(self.socket_path))
                    client.sendall(_LENGTHS.pack(0, 0))
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if self._temporary is not None:
            self._temporary.cleanup()
