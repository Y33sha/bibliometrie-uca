"""Téléchargement du dump CSV public DOAJ + helpers d'URL de fiche.

Le dump CSV (toutes les revues DOAJ, https://doaj.org/csv) est la **source de vérité** pour `journals.doaj_payload` / `is_in_doaj` : il est importé par `application/pipeline/publishers_journals/import_journals_from_doaj_dump` (et, sur fichier local, par la CLI `interfaces/cli/imports/import_doaj_csv`).

`doaj_payload` est stocké aux **clés du dump CSV** ; les consommateurs SQL en dépendent (`doaj_payload->>'X'`, front `READABLE_DOAJ_FIELDS`, audit APC qui requête `doaj_payload->>'APC amount'`).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator

import httpx

from infrastructure.sources.http_status import raise_for_status

DOAJ_CSV_DUMP_URL = "https://doaj.org/csv"
"""Dump CSV public de toutes les revues DOAJ (généré à la volée par DOAJ)."""


def fetch_doaj_dump(
    dest_path: str,
    *,
    user_agent: str,
    logger: logging.Logger,
    url: str = DOAJ_CSV_DUMP_URL,
    timeout: float = 180.0,
) -> None:
    """Télécharge le dump CSV DOAJ en streaming vers `dest_path`.

    Lève `httpx.HTTPError` en cas d'échec — pas de fallback gracieux ici, le caller décide (on ne veut pas importer un dump tronqué).
    """
    logger.info("Téléchargement du dump DOAJ depuis %s …", url)
    with httpx.stream(
        "GET",
        url,
        headers={"User-Agent": user_agent},
        timeout=timeout,
        # Le dump n'est pas servi par doaj.org : la requête est redirigée vers un lien
        # signé, à durée limitée, sur le stockage objet d'Amazon Web Services.
        follow_redirects=True,
    ) as resp:
        raise_for_status(resp)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                f.write(chunk)
    logger.info("Dump DOAJ téléchargé : %s", dest_path)


def read_doaj_dump_rows(path: str) -> Iterator[dict[str, str]]:
    """Itère les rows du dump CSV DOAJ en dicts `{colonne: valeur}`.

    Générateur : le fichier reste ouvert tant qu'on itère (l'import consomme tout en une passe). Mutualisé entre la CLI (fichier local) et le pipeline (dump téléchargé)."""
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f)
