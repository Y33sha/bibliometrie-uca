"""Sonde de vivacité d'un processus, par son numéro."""

import os


def is_pid_alive(pid: int) -> bool:
    """Vrai si le processus `pid` existe encore.

    Sous POSIX, `os.kill(pid, 0)` interroge le système sans envoyer de signal : il lève `ProcessLookupError` si le processus a disparu, et `PermissionError` s'il appartient à un autre utilisateur — un refus qui prouve son existence.

    Sous Windows, le signal 0 vaut `CTRL_C_EVENT` : le même appel envoie un Ctrl-C à tous les processus attachés à la console. La sonde vise donc les seuls systèmes POSIX, qui sont ceux du déploiement.
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
