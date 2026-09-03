"""Sonde de vivacité d'un processus, par son numéro."""

import os


def is_pid_alive(pid: int) -> bool:
    """Vrai si le processus `pid` existe encore.

    `os.kill(pid, 0)` n'envoie aucun signal : il ne fait qu'interroger le système. Il lève `ProcessLookupError` si le processus n'existe plus, et `PermissionError` s'il appartient à un autre utilisateur — un refus qui prouve son existence.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
