"""Écriture sur disque d'un dump téléchargé, bornée en octets.

Le fichier transite par le répertoire temporaire, monté en mémoire et compté sur celle du conteneur : une réponse sans fin y épuiserait la mémoire du processus.
"""

from __future__ import annotations

import httpx2


class DumpDownloadError(Exception):
    """Le téléchargement d'un dump sort de ce qu'on en attend : destination imprévue ou réponse qui dépasse le plafond d'octets."""


def write_capped(resp: httpx2.Response, dest_path: str, max_bytes: int, *, label: str) -> int:
    """Écrit le corps de la réponse dans `dest_path` et rend le nombre d'octets écrits.

    Lève `DumpDownloadError` au franchissement du plafond, sans lire la suite. Le fichier partiel reste sur le disque : son effacement appartient à l'appelant, qui l'a créé. `label` nomme le dump dans le message d'erreur.
    """
    written = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_bytes(chunk_size=1 << 16):
            written += len(chunk)
            if written > max_bytes:
                raise DumpDownloadError(
                    f"Le dump {label} dépasse le plafond de {max_bytes} octets. Relever le "
                    "plafond si le dump a simplement grossi."
                )
            f.write(chunk)
    return written
