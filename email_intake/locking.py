"""Process-held guard serializes marker creation, recovery and removal."""
from contextlib import contextmanager
import json
import os

from .ledger import safe_path
from .contract import strict_json


class LockError(FileExistsError):
    pass


def process_alive(pid):
    """Unknown ownership/liveness is busy. PID reuse also refuses recovery."""
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER means there is no such process. Access
            # denied and every other unknown result must remain locked.
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return True
    return True


@contextmanager
def guard(root):
    # This file is permanent. Removing an OS-locked file would let a competing
    # run lock a different inode; closing before removal would create a race.
    fd = os.open(safe_path(root / ".intake-guard"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockError("CONFLICT") from None
        # OS ownership is released even on a hard kill.
        yield
    finally:
        os.close(fd)


@contextmanager
def exclusive(root, *, break_lock=False):
    with guard(root):
        path = safe_path(root / ".intake-lock")
        if path.exists():
            if not break_lock:
                raise LockError("CONFLICT")
            try:
                with path.open("rb") as stream:
                    data = stream.read(1025)
                marker = strict_json(data) if len(data) <= 1024 else None
                if not isinstance(marker, dict) or set(marker) != {"pid"} or process_alive(marker["pid"]):
                    raise LockError("CONFLICT")
            except (ValueError, OSError):
                # Legacy empty, malformed, unreadable or unknown-owner markers
                # cannot prove that an older runner is dead.
                raise LockError("CONFLICT") from None
            path.unlink()
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (json.dumps({"pid": os.getpid()}) + "\n").encode("ascii"))
            os.fsync(fd)
            yield
        finally:
            os.close(fd)
            path.unlink()
