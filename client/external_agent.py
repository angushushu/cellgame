"""Run a local agent using one JSON request and response per line."""
import asyncio
import concurrent.futures
import json
import subprocess
import time

import numpy as np

from cellgame.client.local_service import controller_message, response_actions
from cellgame.shared.models import INTENTION_DTYPE


class ExternalAgentExecutor:
    def __init__(self, command, timeout=2.0):
        if not command:
            raise ValueError("external agent command is empty")
        self.command = list(command)
        self.timeout = timeout
        self.ns = {"external_agent": True}  # same ready indicator as RuleExecutor
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.process = None
        self.last_error = None
        self.last_duration_ms = None
        self.timed_out = False

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def _exchange(self, batch):
        if self.process is not None and self.process.poll() is not None:
            self.close()
        if self.process is None:
            self.process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1)
        process = self.process
        message = controller_message(batch)
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()
        line = process.stdout.readline(4 * 1024 * 1024 + 1)
        if not line or len(line) > 4 * 1024 * 1024 or not line.endswith("\n"):
            raise ValueError("external agent returned no valid response line")
        reply = json.loads(line)
        return response_actions(reply, batch)

    async def run(self, batch):
        loop = asyncio.get_running_loop()
        start = time.monotonic()
        self.timed_out = False
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(self.pool, self._exchange, batch), self.timeout)
            self.last_error = None
            return result
        except asyncio.TimeoutError:
            self.timed_out = True
            self.close()
            self.last_error = "外部规则超时，进程已停止；下次将重新启动"
        except Exception as exc:
            self.close()
            self.last_error = f"外部规则出错: {exc}"
        finally:
            self.last_duration_ms = (time.monotonic() - start) * 1000
        return np.empty((0,), dtype=INTENTION_DTYPE)
