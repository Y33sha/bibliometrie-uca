"""Téléchargement et lecture du dump du Research Organization Registry (ROR).

Le ROR publie son dump sur Zenodo, dans la communauté `ror-data` : une archive zip par version, qui contient le registre en JSON et en CSV. La lecture parcourt le CSV ligne à ligne. Le JSON demande plus d'un gigaoctet de mémoire.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import httpx2

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType
from domain.types import as_mapping, as_sequence, as_str
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.dump_download import DumpDownloadError, write_capped
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.http_status import raise_for_status

ZENODO_HOST = "zenodo.org"

MAX_DUMP_BYTES = 256 * 1024 * 1024
"""Plafond d'octets acceptés pour l'archive, qui pèse une quarantaine de mégaoctets."""

_ARCHIVE_SUFFIX = "-ror-data.zip"
_CSV_SUFFIX = "-ror-data.csv"


@dataclass(frozen=True, slots=True)
class RorDumpFile:
    """Archive d'une version du dump : son titre Zenodo (« ROR Data v2.14 »…) et son URL de téléchargement."""

    title: str
    url: str


def find_latest_ror_dump(*, user_agent: str) -> RorDumpFile:
    """Archive de la version la plus récente du dump, d'après l'API Zenodo.

    Lève `DumpDownloadError` si la réponse ne désigne pas d'archive sur `zenodo.org`.
    """
    body = as_mapping(
        http_request_with_retry(
            "GET",
            API_BASE_URLS["zenodo_ror"],
            params={"sort": "newest", "size": 1},
            headers={"User-Agent": user_agent},
            label="ror dump",
        )
    )
    hits = as_sequence(as_mapping(body.get("hits")).get("hits"))
    if not hits:
        raise DumpDownloadError("Aucune version du dump ROR sur Zenodo.")
    record = as_mapping(hits[0])
    title = as_str(as_mapping(record.get("metadata")).get("title")) or ""
    for file in as_sequence(record.get("files")):
        entry = as_mapping(file)
        if (as_str(entry.get("key")) or "").endswith(_ARCHIVE_SUFFIX):
            url = as_str(as_mapping(entry.get("links")).get("self")) or ""
            if httpx2.URL(url).host != ZENODO_HOST:
                raise DumpDownloadError(f"L'archive du dump ROR est hors de {ZENODO_HOST} : {url}")
            return RorDumpFile(title=title, url=url)
    raise DumpDownloadError(f"Aucune archive `*{_ARCHIVE_SUFFIX}` dans la version « {title} ».")


def fetch_ror_dump(
    dest_path: str,
    *,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 180.0,
    max_bytes: int = MAX_DUMP_BYTES,
) -> RorDumpFile:
    """Télécharge l'archive de la version la plus récente du dump vers `dest_path`, et la rend.

    Lève `httpx2.HTTPError` sur un échec de transport ou un statut d'erreur, redirection comprise, et `DumpDownloadError` au-delà de `max_bytes`.
    """
    dump = find_latest_ror_dump(user_agent=user_agent)
    logger.info("Téléchargement du dump ROR (%s) depuis %s …", dump.title, dump.url)
    with (
        httpx2.Client(timeout=timeout, follow_redirects=False) as client,
        client.stream("GET", dump.url, headers={"User-Agent": user_agent}) as resp,
    ):
        raise_for_status(resp)
        written = write_capped(resp, dest_path, max_bytes, label="ROR")
    logger.info("Dump ROR téléchargé : %s (%d octets)", dest_path, written)
    return dump


def read_ror_dump(archive_path: str) -> Iterator[RorOrganization]:
    """Itère les organisations du CSV de l'archive.

    Lève `ValueError` sur une ligne inexploitable : un dump incomplet ne doit pas remplacer le référentiel.
    """
    with zipfile.ZipFile(archive_path) as archive:
        member = next((n for n in archive.namelist() if n.endswith(_CSV_SUFFIX)), None)
        if member is None:
            raise ValueError(f"Aucun fichier `*{_CSV_SUFFIX}` dans {archive_path}.")
        with archive.open(member) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                yield parse_ror_row(row)


def parse_ror_row(row: Mapping[str, str]) -> RorOrganization:
    """Organisation d'une ligne du CSV du dump (schéma v2)."""
    relations = _parse_relationships(row["relationships"])
    return RorOrganization(
        ror_id=RorId(row["id"]),
        name=row["names.types.ror_display"].strip(),
        country_code=row["locations.geonames_details.country_code"].split(";")[0].strip().lower(),
        types=frozenset(RorType(t.strip()) for t in row["types"].split(";") if t.strip()),
        status=RorStatus(row["status"]),
        parent_ids=relations.get("parent", frozenset()),
        child_ids=relations.get("child", frozenset()),
    )


def _parse_relationships(cell: str) -> dict[str, frozenset[RorId]]:
    """Relations d'une ligne par type : `child: <url>, <url>; parent: <url>` → `{type: identifiants}`."""
    relations: dict[str, frozenset[RorId]] = {}
    for segment in cell.split(";"):
        kind, _, urls = segment.partition(":")
        ids = frozenset(RorId(u.strip()) for u in urls.split(",") if u.strip())
        if ids:
            relations[kind.strip()] = ids
    return relations
