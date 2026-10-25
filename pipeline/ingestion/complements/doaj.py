"""Téléchargement et lecture du dump CSV public du DOAJ.

Le dump CSV (toutes les revues DOAJ, https://doaj.org/csv) est la **source de vérité** pour `serials.doaj_payload` / `is_in_doaj` : il est importé par `pipeline/transformation/publishing/serials/enrich_serials_from_doaj` (et, sur fichier local, par la CLI `interfaces/cli/imports/import_doaj_csv`).

`doaj_payload` est stocké aux **clés du dump CSV** ; les consommateurs SQL en dépendent (`doaj_payload->>'X'`, front `READABLE_DOAJ_FIELDS`, audit APC qui requête `doaj_payload->>'APC amount'`).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from pipeline.http.dump_download import downloaded_dump

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


def read_doaj_dump_rows(path: str) -> Iterator[dict[str, str]]:
    """Itère les rows du dump CSV DOAJ en dicts `{colonne: valeur}`.

    Générateur : le fichier reste ouvert tant qu'on itère (l'import consomme tout en une passe). Mutualisé entre la CLI (fichier local) et le pipeline (dump téléchargé)."""
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f)


@contextmanager
def downloaded_doaj_dump(
    *, user_agent: str, logger: logging.Logger
) -> Iterator[Iterator[dict[str, str]]]:
    """Télécharge le dump CSV DOAJ et rend ses rows, le temps du bloc.

    Le dump transite par un fichier temporaire, que le module CSV relit : un enregistrement peut contenir des sauts de ligne dans ses champs. Lève `DumpUnavailableError` quand le téléchargement échoue, avant que le bloc ne commence.
    """
    with downloaded_dump(
        DOAJ_CSV_DUMP_URL,
        file_name="doaj.csv",
        label="DOAJ",
        user_agent=user_agent,
        logger=logger,
        max_bytes=MAX_DUMP_BYTES,
        allowed_redirect_hosts=ALLOWED_DUMP_HOSTS,
    ) as path:
        yield read_doaj_dump_rows(path)
