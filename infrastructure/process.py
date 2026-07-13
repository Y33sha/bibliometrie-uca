"""Sonde de vivacité d'un process par PID (POSIX + Windows)."""

import os
import sys


def is_pid_alive(pid: int) -> bool:
    """True si le process `pid` existe encore.

    POSIX : `os.kill(pid, 0)` lève `ProcessLookupError` si mort, `PermissionError` si le process existe mais appartient à un autre user (considéré vivant).

    Windows : `os.kill(pid, 0)` y appelle `TerminateProcess` (il tuerait le process). La sonde passe par `OpenProcess` + `GetExitCodeProcess` : un process vivant renvoie `STILL_ACTIVE` (259), un process terminé renvoie son code de sortie.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
