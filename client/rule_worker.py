"""Persistent local Python rule worker. Process isolation is not a sandbox."""
import multiprocessing

from cellgame.client.rule_loader import load_rule

PARENT_CHECK_SECONDS = 1.0


def _next_batch(connection, parent):
    """Wait for the next batch; None when the client is gone.

    On Windows a blocked recv() may never notice that the client process was
    killed, so poll with a timeout and check the parent in between.
    """
    while not connection.poll(PARENT_CHECK_SECONDS):
        if parent is not None and not parent.is_alive():
            return None
    return connection.recv()


def serve_rule(connection, source):
    parent = multiprocessing.parent_process()
    try:
        decide = load_rule(source)
        connection.send((True, None))
        while True:
            try:
                batch = _next_batch(connection, parent)
            except (EOFError, OSError):
                break
            if batch is None:
                break
            try:
                result = decide(
                    batch["cells"], batch["neighborhood"], batch["env"],
                    batch["constraints"], batch["tick"],
                    observation=batch.get("observation"))
                connection.send((True, result))
            except BaseException as exc:
                connection.send((False, f"{type(exc).__name__}: {exc}"))
    except BaseException as exc:
        try:
            connection.send((False, f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()
