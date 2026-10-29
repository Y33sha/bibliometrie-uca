"""Téléchargement d'un dump de référentiel (ROR, DOAJ), borné en octets et en destinations.

Le fichier transite par le répertoire temporaire, monté en mémoire et compté sur celle du conteneur : une réponse sans fin y épuiserait la mémoire du processus.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2

from pipeline.http.http_status import raise_for_status
from pipeline.http.tls import tls_context

_MAX_REDIRECTS = 3
"""Nombre maximal de redirections, contre une redirection circulaire. La liste des hôtes autorisés fait la sécurité."""


class DumpUnavailableError(Exception):
    """Un dump de référentiel (ROR, DOAJ) est inaccessible : échec du réseau, du serveur, ou réponse inattendue."""


class DumpDownloadError(Exception):
    """Le téléchargement d'un dump sort de ce qu'on en attend : destination imprévue ou réponse qui dépasse le plafond d'octets."""


def write_capped(resp: httpx2.Response, dest_path: str, max_bytes: int, *, label: str) -> int:
    """Écrit le corps de la réponse dans `dest_path` et renvoie le nombre d'octets écrits.

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


def _redirect_target(
    resp: httpx2.Response, current: httpx2.URL, allowed_hosts: frozenset[str], *, label: str
) -> httpx2.URL:
    """Destination d'une redirection, si elle est prévue.

    Lève `DumpDownloadError` quand l'en-tête manque ou quand l'hôte visé est absent de `allowed_hosts`. Le contrôle précède la requête : aucune connexion n'est ouverte vers un hôte non prévu.
    """
    location = resp.headers.get("location")
    if not location:
        raise DumpDownloadError(f"Redirection sans destination depuis {current}.")
    target = current.join(location)
    if target.host not in allowed_hosts:
        raise DumpDownloadError(
            f"Le téléchargement du dump {label} est redirigé vers {target.host}, hôte absent de "
            f"la liste des destinations attendues ({', '.join(sorted(allowed_hosts))}). "
            "Vérifier le changement côté éditeur du dump avant d'inscrire l'hôte."
        )
    return target


def download_dump(
    url: str,
    dest_path: str,
    *,
    label: str,
    user_agent: str,
    logger: logging.Logger,
    max_bytes: int,
    allowed_redirect_hosts: frozenset[str] = frozenset(),
    timeout: float = 180.0,
) -> None:
    """Télécharge le dump `label` de `url` vers `dest_path`, en streaming, borné à `max_bytes`.

    Une redirection est suivie seulement vers `allowed_redirect_hosts`. Sans hôte autorisé, elle reste un statut d'erreur. Lève `httpx2.HTTPError` sur un échec de transport ou un statut d'erreur, `DumpDownloadError` quand le téléchargement sort de ce qu'on en attend.
    """
    logger.info("Téléchargement du dump %s depuis %s", label, url, extra={"detail": True})
    target = httpx2.URL(url)
    headers = {"User-Agent": user_agent}
    with httpx2.Client(timeout=timeout, follow_redirects=False, verify=tls_context()) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            with client.stream("GET", target, headers=headers) as resp:
                if resp.is_redirect and allowed_redirect_hosts:
                    target = _redirect_target(resp, target, allowed_redirect_hosts, label=label)
                    continue
                raise_for_status(resp)
                written = write_capped(resp, dest_path, max_bytes, label=label)
            logger.info(
                "Dump %s téléchargé : %s (%d octets)",
                label,
                dest_path,
                written,
                extra={"detail": True},
            )
            return
    raise DumpDownloadError(
        f"Le téléchargement du dump {label} dépasse {_MAX_REDIRECTS} redirections depuis {url}."
    )


@contextmanager
def downloaded_dump(
    url: str,
    *,
    file_name: str,
    label: str,
    user_agent: str,
    logger: logging.Logger,
    max_bytes: int,
    allowed_redirect_hosts: frozenset[str] = frozenset(),
) -> Iterator[str]:
    """Télécharge le dump dans un fichier temporaire `file_name` et renvoie son chemin, le temps du bloc.

    Le répertoire temporaire est le seul emplacement en écriture du conteneur (`tmpfs` sur `/tmp`). Le fichier est supprimé à la sortie du bloc. Lève `DumpUnavailableError` quand le téléchargement échoue, avant que le bloc ne commence.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / file_name)
        try:
            download_dump(
                url,
                path,
                label=label,
                user_agent=user_agent,
                logger=logger,
                max_bytes=max_bytes,
                allowed_redirect_hosts=allowed_redirect_hosts,
            )
        except (httpx2.HTTPError, DumpDownloadError) as e:
            raise DumpUnavailableError(str(e)) from e
        yield path
