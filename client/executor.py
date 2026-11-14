"""Persistent local rule worker with a recoverable process timeout.

This isolates failures, not permissions: player code is still trusted code.
"""
import asyncio
import concurrent.futures
import multiprocessing as mp
import threading
import time

import numpy as np

from cellgame.shared.models import INTENTION_DTYPE
from cellgame.species.runtime import to_intentions, world_size
from .rule_worker import serve_rule


class RuleExecutor:
    def __init__(self, timeout=2.0):
        self.timeout = timeout
        self.ns = {}
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        self.context = mp.get_context("spawn")
        self.process = None
        self.connection = None
        self.source = None
        self.service_url = None
        self.last_error = None
        self.last_duration_ms = None
        self.timed_out = False

    @staticmethod
    def _stop(process, connection):
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        if connection is not None:
            connection.close()

    def _start(self, source):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=serve_rule, args=(child, source), daemon=True)
        try:
            process.start()
            child.close()
            if not parent.poll(10):
                raise TimeoutError("规则加载超时")
            ok, message = parent.recv()
            if not ok:
                raise ValueError(message)
            return process, parent
        except BaseException:
            child.close()
            if process.pid is not None:
                self._stop(process, parent)
            else:
                parent.close()
            raise

    def load(self, source):
        with self.lock:
            process, connection = self._start(source)
            self._stop(self.process, self.connection)
            self.process, self.connection = process, connection
            self.source = source
            self.service_url = None
            self.ns = {"decide": True}
            self.last_error = None

    def load_service(self, url):
        from .local_service import validate_service_url
        url = validate_service_url(url)
        with self.lock:
            self._stop(self.process, self.connection)
            self.process, self.connection = None, None
            self.service_url = url
            self.ns = {"service": True}
            self.last_error = None

    def _call(self, batch):
        with self.lock:
            if self.service_url:
                from .local_service import call_service
                return call_service(self.service_url, batch, self.timeout)
            if self.process is None or not self.process.is_alive():
                self._stop(self.process, self.connection)
                self.process, self.connection = self._start(self.source)
            try:
                self.connection.send(batch)
                if not self.connection.poll(self.timeout):
                    raise TimeoutError("规则执行超时，本 tick 无动作")
                ok, result = self.connection.recv()
                if not ok:
                    raise ValueError(result)
                return to_intentions(result, batch["cells"], *world_size(batch))
            except (TimeoutError, EOFError, BrokenPipeError, OSError):
                self._stop(self.process, self.connection)
                self.process, self.connection = None, None
                raise

    def close(self):
        with self.lock:
            self._stop(self.process, self.connection)
            self.process, self.connection = None, None
            self.ns = {}
        self.pool.shutdown(wait=False, cancel_futures=True)

    async def run(self, batch):
        """Returns an INTENTION_DTYPE structured array (possibly empty)."""
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        self.timed_out = False
        try:
            result = await loop.run_in_executor(self.pool, self._call, batch)
            self.last_error = None
            return result
        except TimeoutError:
            self.timed_out = True
            self.last_error = "控制器响应超时，本 tick 无动作"
            return np.empty((0,), dtype=INTENTION_DTYPE)
        except Exception as e:  # noqa: BLE001 - reported to the console
            self.last_error = f"规则出错: {e}"
            return np.empty((0,), dtype=INTENTION_DTYPE)
        finally:
            self.last_duration_ms = (time.monotonic() - t0) * 1000
