"""Téléchargement et lecture de la table ISSN-L de l'ISSN International Centre.

La table donne l'ISSN-L de chaque ISSN attribué, et fait autorité sur `serial_issns.issnl`. La phase `publishing` l'importe (`import_issnl_table`).

Le zip contient deux fichiers tabulés de même contenu, ISSN → ISSN-L et ISSN-L → ISSN. Seul le premier est lu.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager

from pipeline.http.dump_download import downloaded_dump

ISSNL_TABLE_URL = "https://portal.issn.org/public/issnltables.zip"
"""Table ISSN-L publique, mise à jour chaque jour."""

MAX_TABLE_BYTES = 256 * 1024 * 1024
"""Plafond d'octets acceptés pour le zip, qui pèse une trentaine de mégaoctets."""

_ISSN_TO_ISSNL_FILE = re.compile(r"ISSN[-_]to[-_]ISSN-L", re.IGNORECASE)


def read_issnl_table(path: str) -> Iterator[tuple[str, str]]:
    """Itère les couples (ISSN, ISSN-L) du fichier ISSN → ISSN-L du zip, tels qu'écrits. Un zip sans ce fichier ne donne aucun couple."""
    with zipfile.ZipFile(path) as archive:
        name = next((n for n in archive.namelist() if _ISSN_TO_ISSNL_FILE.search(n)), None)
        if name is None:
            return
        with archive.open(name) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) >= 2:
                    yield fields[0].strip().upper(), fields[1].strip().upper()


@contextmanager
def downloaded_issnl_table(
    *, user_agent: str, logger: logging.Logger
) -> Iterator[Iterator[tuple[str, str]]]:
    """Télécharge la table ISSN-L et renvoie ses couples (ISSN, ISSN-L), le temps du bloc. Lève `DumpUnavailableError` quand le téléchargement échoue, avant le début du bloc."""
    with downloaded_dump(
        ISSNL_TABLE_URL,
        file_name="issnltables.zip",
        label="table ISSN-L",
        user_agent=user_agent,
        logger=logger,
        max_bytes=MAX_TABLE_BYTES,
    ) as path:
        yield read_issnl_table(path)
