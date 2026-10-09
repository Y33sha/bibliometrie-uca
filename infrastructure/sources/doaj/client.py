"""Téléchargement du dump CSV public DOAJ + helpers d'URL de fiche.

Le dump CSV (toutes les revues DOAJ, https://doaj.org/csv) est la **source de vérité** pour `journals.doaj_payload` / `is_in_doaj` : il est importé par `application/pipeline/publishers_journals/import_journals_from_doaj_dump` (et, sur fichier local, par la CLI `interfaces/cli/imports/import_doaj_csv`).

`doaj_payload` est stocké aux **clés du dump CSV** ; les consommateurs SQL en dépendent (`doaj_payload->>'X'`, front `READABLE_DOAJ_FIELDS`, audit APC qui requête `doaj_payload->>'APC amount'`).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator

import httpx2

from infrastructure.sources.dump_download import DumpDownloadError, write_capped
from infrastructure.sources.http_status import raise_for_status

DOAJ_CSV_DUMP_URL = "https://doaj.org/csv"
"""Dump CSV public de toutes les revues DOAJ (généré à la volée par DOAJ)."""

ALLOWED_DUMP_HOSTS = frozenset({"doaj.org", "doaj-live-journal-csv.s3.amazonaws.com"})
"""Hôtes que le téléchargement du dump accepte de joindre.

C'est la seule requête sortante du projet qui suive une redirection : le dump n'est pas servi par `doaj.org`, qui renvoie vers un lien signé, à durée limitée, sur son stockage objet. Partout ailleurs un statut de redirection est traité comme une erreur, ce qui fait des URL écrites dans le code la liste des hôtes joignables. Nommer ici la destination attendue rend cette propriété vraie de cette requête aussi : une redirection ailleurs échoue en nommant l'hôte rencontré, plutôt que d'étendre en silence la surface sortante.
"""

MAX_DUMP_BYTES = 256 * 1024 * 1024
"""Plafond d'octets acceptés pour le dump.

Le dump pèse une trentaine de mégaoctets ; le plafond laisse un ordre de grandeur de marge et reste loin de ce dont dispose le conteneur.
"""

_MAX_REDIRECTS = 3
"""Bornes du nombre de sauts. La garantie tient à la liste d'hôtes ; ce plafond ferme la boucle qu'une redirection circulaire ouvrirait."""


def _redirect_target(resp: httpx2.Response, current: httpx2.URL) -> httpx2.URL:
    """Destination d'une redirection, si elle est prévue.

    Lève `DumpDownloadError` quand l'en-tête manque ou quand l'hôte visé n'est pas de la liste — le contrôle précède la requête, si bien qu'aucune connexion n'est ouverte vers un hôte non prévu.
    """
    location = resp.headers.get("location")
    if not location:
        raise DumpDownloadError(f"Redirection sans destination depuis {current}.")
    target = current.join(location)
    if target.host not in ALLOWED_DUMP_HOSTS:
        raise DumpDownloadError(
            f"Le téléchargement du dump DOAJ est redirigé vers {target.host}, hôte absent de "
            f"la liste des destinations attendues ({', '.join(sorted(ALLOWED_DUMP_HOSTS))}). "
            "Vérifier le changement côté DOAJ avant d'inscrire l'hôte."
        )
    return target


def fetch_doaj_dump(
    dest_path: str,
    *,
    user_agent: str,
    logger: logging.Logger,
    url: str = DOAJ_CSV_DUMP_URL,
    timeout: float = 180.0,
    max_bytes: int = MAX_DUMP_BYTES,
) -> None:
    """Télécharge le dump CSV DOAJ en streaming vers `dest_path`.

    Les redirections sont suivies une à une plutôt que par le client : chaque destination est confrontée à `ALLOWED_DUMP_HOSTS` avant qu'une requête ne parte, et le corps reçu est borné par `max_bytes`.

    Lève `httpx2.HTTPError` sur un échec de transport ou un statut d'erreur, `DumpDownloadError` quand le téléchargement sort de ce qu'on en attend — pas de repli gracieux ici, l'appelant décide (on ne veut pas importer un dump tronqué).
    """
    logger.info("Téléchargement du dump DOAJ depuis %s …", url)
    target = httpx2.URL(url)
    headers = {"User-Agent": user_agent}
    with httpx2.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            with client.stream("GET", target, headers=headers) as resp:
                if resp.is_redirect:
                    target = _redirect_target(resp, target)
                    continue
                raise_for_status(resp)
                written = write_capped(resp, dest_path, max_bytes, label="DOAJ")
            logger.info("Dump DOAJ téléchargé : %s (%d octets)", dest_path, written)
            return
    raise DumpDownloadError(
        f"Le téléchargement du dump DOAJ dépasse {_MAX_REDIRECTS} redirections depuis {url}."
    )


def read_doaj_dump_rows(path: str) -> Iterator[dict[str, str]]:
    """Itère les rows du dump CSV DOAJ en dicts `{colonne: valeur}`.

    Générateur : le fichier reste ouvert tant qu'on itère (l'import consomme tout en une passe). Mutualisé entre la CLI (fichier local) et le pipeline (dump téléchargé)."""
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f)
