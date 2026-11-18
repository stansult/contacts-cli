"""Sequential private read process with bounded IPC and deterministic cleanup."""

import json
import os
import selectors
import subprocess
import sys
import time

MAX_FRAME = 16 * 1024 * 1024


class PersistentReader:
    """One sequential read at a time; parent bounds startup, IPC, and network work."""

    def __init__(self, command=None):
        self.command = command or [sys.executable, "-m", "contacts_cli.read_worker", "--persistent"]
        self.process = None
        self.closed = False
        self.sequence = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()

    def close(self):
        self.closed = True
        self._stop()

    def request(self, payload, *, seconds=15):
        if self.closed:
            raise RuntimeError("Reader is closed")
        deadline = time.monotonic() + seconds
        self.sequence += 1
        try:
            if self.process is None:
                self.process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                    os.set_blocking(pipe.fileno(), False)
            packet = {"id": self.sequence, "payload": {**payload, "timeout": seconds}}
            wire = json.dumps(packet).encode() + b"\n"
            if len(wire) > MAX_FRAME:
                raise ValueError("Request exceeds worker frame limit")
            result = self._exchange(wire, deadline)
            if not isinstance(result, dict) or result.get("id") != self.sequence:
                raise ValueError("Unexpected response ID")
            if "error" in result:
                self._stop()
                return {"error": result["error"]}
            value = result.get("result")
            if not isinstance(value, dict):
                raise ValueError("Invalid worker result")
            return value
        except BaseException:
            self._stop()
            raise

    def _exchange(self, wire, deadline):
        process = self.process
        output, offset = bytearray(), 0
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdin, selectors.EVENT_WRITE)
            ready.register(process.stdout, selectors.EVENT_READ)
            ready.register(process.stderr, selectors.EVENT_READ)
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("Read deadline exceeded")
                for key, _ in ready.select(left):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        offset += os.write(pipe.fileno(), wire[offset : offset + 65536])
                        if offset == len(wire):
                            ready.unregister(pipe)
                    else:
                        chunk = os.read(pipe.fileno(), 65536)
                        if not chunk:
                            ready.unregister(pipe)
                            if pipe is process.stdout:
                                raise RuntimeError("Read worker exited without a reply")
                        elif pipe is process.stdout:
                            output.extend(chunk)
                            if len(output) > MAX_FRAME:
                                raise ValueError("Response exceeds worker frame limit")
                        # Drain stderr without retaining potentially sensitive output.
                if time.monotonic() >= deadline:
                    raise TimeoutError("Read deadline exceeded")
                if b"\n" in output:
                    line, trailing = output.split(b"\n", 1)
                    if trailing or offset != len(wire):
                        raise ValueError("Unexpected response framing")
                    return json.loads(line)
