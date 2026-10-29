"""Téléchargement et lecture du dump CSV public du DOAJ.

Le dump liste toutes les revues du DOAJ (https://doaj.org/csv) et fait autorité sur `serials.doaj_payload` et `is_in_doaj`. La phase `publishing` l'importe (`enrich_serials_from_doaj`), comme la commande `import_doaj_csv` sur fichier local.

`doaj_payload` garde les clés du dump CSV : des requêtes SQL, l'interface (`READABLE_DOAJ_FIELDS`) et l'audit des APC (`doaj_payload->>'APC amount'`) les lisent.
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

C'est la seule requête sortante du projet qui suit une redirection : `doaj.org` renvoie vers un lien signé, à durée limitée, sur son stockage objet. Ailleurs, une redirection est une erreur, si bien que les URL écrites dans le code sont la liste des hôtes joignables. La liste garde cette propriété ici : une redirection vers un autre hôte échoue en le nommant.
"""

MAX_DUMP_BYTES = 256 * 1024 * 1024
"""Plafond d'octets acceptés pour le dump.

Le dump pèse une trentaine de mégaoctets ; le plafond laisse un ordre de grandeur de marge et reste loin de ce dont dispose le conteneur.
"""


def read_doaj_dump_rows(path: str) -> Iterator[dict[str, str]]:
    """Itère les lignes du dump CSV, chacune par colonne.

    Le fichier reste ouvert le temps de l'itération. La commande sur fichier local et le pipeline partagent cette lecture."""
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f)


@contextmanager
def downloaded_doaj_dump(
    *, user_agent: str, logger: logging.Logger
) -> Iterator[Iterator[dict[str, str]]]:
    """Télécharge le dump CSV du DOAJ et rend ses lignes, le temps du bloc.

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
