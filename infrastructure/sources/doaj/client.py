"""Téléchargement du dump CSV public DOAJ + helpers d'URL de fiche.

Le dump CSV (toutes les revues DOAJ, https://doaj.org/csv) est la **source de vérité** pour `journals.doaj_payload` / `is_in_doaj` : il est importé par `application/pipeline/publishers_journals/import_journals_from_doaj_dump` (et, sur fichier local, par la CLI `interfaces/cli/imports/import_doaj_csv`).

`doaj_payload` est stocké aux **clés du dump CSV** ; les consommateurs SQL en dépendent (`doaj_payload->>'X'`, front `READABLE_DOAJ_FIELDS`, audit APC qui requête `doaj_payload->>'APC amount'`).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator

import httpx

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
        follow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                f.write(chunk)
    logger.info("Dump DOAJ téléchargé : %s", dest_path)


def read_doaj_dump_rows(path: str) -> Iterator[dict[str, str]]:
    """Itère les rows du dump CSV DOAJ en dicts `{colonne: valeur}`.

    Générateur : le fichier reste ouvert tant qu'on itère (l'import consomme tout en une passe). Mutualisé entre la CLI (fichier local) et le pipeline (dump téléchargé)."""
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f)


DOAJ_TOC_URL = "https://doaj.org/toc/{id}"
"""URL canonique d'une fiche journal DOAJ (table des matières)."""


def build_doaj_toc_url(doaj_id: str | None) -> str | None:
    """Reconstruit l'URL de la fiche DOAJ à partir d'un `DOAJ id`.

    Retourne `None` si l'id est absent — cas d'un payload sans `DOAJ id` (le dump CSV stocke l'URL toute faite sous `URL in DOAJ`).
    """
    if not doaj_id:
        return None
    return DOAJ_TOC_URL.format(id=doaj_id)


def resolve_doaj_url(payload_url: str | None, doaj_id: str | None) -> str | None:
    """URL de fiche DOAJ à partir d'un payload, quelle que soit sa provenance.

    Privilégie l'URL toute faite (`'URL in DOAJ'` du dump CSV) et la reconstruit depuis le `'DOAJ id'` à défaut. `None` si ni l'un ni l'autre.
    """
    return payload_url or build_doaj_toc_url(doaj_id)
