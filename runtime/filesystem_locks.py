"""OS-released locks for the same file across service processes."""
from contextlib import ExitStack, contextmanager
import getpass
import hashlib
import os
from pathlib import Path
import tempfile


@contextmanager
def locked_paths(paths):
    account = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / ("acs-file-locks-" + account)
    directory.mkdir(mode=0o700, exist_ok=True)
    names = sorted({hashlib.sha256(os.path.normcase(str(path.resolve())).encode()).hexdigest() for path in paths})
    with ExitStack() as stack:
        for name in names:
            lock = stack.enter_context((directory / name).open("a+b"))
            if os.name == "nt":
                import msvcrt
                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                stack.callback(_unlock_windows, lock)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
                stack.callback(fcntl.flock, lock, fcntl.LOCK_UN)
        yield


def _unlock_windows(lock):
    import msvcrt
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
