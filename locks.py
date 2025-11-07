import os
import time
import errno
import tempfile
from contextlib import contextmanager

try:
    import portalocker
    _HAS_PORTALOCKER = True
except ImportError:
    portalocker = None
    _HAS_PORTALOCKER = False

def get_lock_path(file_path):
    """Get the path for the lock file"""
    lock_dir = os.path.join(tempfile.gettempdir(), 'cloudos_locks')
    os.makedirs(lock_dir, exist_ok=True)
    safe_name = os.path.abspath(file_path).replace(os.sep, '_')
    return os.path.join(lock_dir, f"{safe_name}.lock")

class LockHandle:
    def __init__(self, fh, exclusive: bool, path: str):
        self._fh = fh
        self.exclusive = exclusive
        self._path = path
        self._lockfile = get_lock_path(path) if not _HAS_PORTALOCKER and exclusive else None

    def release(self):
        try:
            if _HAS_PORTALOCKER and self._fh:
                portalocker.unlock(self._fh)
                self._fh.close()
            elif self._lockfile and os.path.exists(self._lockfile):
                os.remove(self._lockfile)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()

def acquire_exclusive_lock(path, timeout=10):
    """Exclusive lock: no other readers/writers."""
    start_time = time.time()

    while True:
        try:
            if _HAS_PORTALOCKER:
                # Create file if it doesn't exist
                if not os.path.exists(path):
                    parent = os.path.dirname(os.path.abspath(path))
                    os.makedirs(parent, exist_ok=True)
                    with open(path, 'a'):
                        pass
                
                fh = open(path, 'r+b')  # Need read+write
                portalocker.lock(fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
                return LockHandle(fh, exclusive=True, path=path)
            else:
                # Fallback: atomic lock file creation
                lockfile = get_lock_path(path)
                try:
                    fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                    return LockHandle(None, exclusive=True, path=path)
                except OSError as e:
                    if e.errno == errno.EEXIST:
                        if time.time() - start_time >= timeout:
                            raise TimeoutError(f"Could not acquire lock on {path} after {timeout} seconds")
                        time.sleep(0.1)
                        continue
                    raise
        except PermissionError as e:
            raise PermissionError(f"Cannot access file {path}. Please check file permissions.") from e
        except Exception as e:
            if time.time() - start_time >= timeout:
                raise TimeoutError(f"Could not acquire lock on {path} after {timeout} seconds")
            time.sleep(0.1)
            continue

def acquire_shared_lock(path, timeout=10):
    """Shared lock: multiple readers allowed."""
    start_time = time.time()

    while True:
        try:
            if _HAS_PORTALOCKER:
                # Create file if it doesn't exist
                if not os.path.exists(path):
                    parent = os.path.dirname(os.path.abspath(path))
                    os.makedirs(parent, exist_ok=True)
                    with open(path, 'a'):
                        pass

                fh = open(path, 'rb')
                portalocker.lock(fh, portalocker.LOCK_SH | portalocker.LOCK_NB)
                return LockHandle(fh, exclusive=False, path=path)
            else:
                # Fallback: check for exclusive lock
                lockfile = get_lock_path(path)
                if not os.path.exists(lockfile):
                    # No exclusive lock, allow shared access
                    return LockHandle(None, exclusive=False, path=path)
                if time.time() - start_time >= timeout:
                    raise TimeoutError(f"Could not acquire shared lock on {path} after {timeout} seconds")
                time.sleep(0.1)
                continue
        except PermissionError as e:
            raise PermissionError(f"Cannot access file {path}. Please check file permissions.") from e
        except Exception as e:
            if time.time() - start_time >= timeout:
                raise TimeoutError(f"Could not acquire shared lock on {path} after {timeout} seconds")
            time.sleep(0.1)
            continue

def release_lock(lockhandle: LockHandle):
    lockhandle.release()