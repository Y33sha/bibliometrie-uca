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

from domain.errors import ValidationError
from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType
from domain.types import as_mapping, as_sequence, as_str
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.dump_download import (
    DumpDownloadError,
    DumpUnavailableError,
    download_dump,
    downloaded_dump,
)
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.http_status import raise_for_status
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS

ZENODO_HOST = "zenodo.org"

MAX_DUMP_BYTES = 256 * 1024 * 1024
"""Plafond d'octets acceptés pour l'archive, qui pèse une quarantaine de mégaoctets."""

_ARCHIVE_SUFFIX = "-ror-data.zip"
_CSV_SUFFIX = "-ror-data.csv"

ROR_DATA_CONCEPT_DOI = "10.5281/zenodo.6347574"
"""DOI conceptuel du dump sur Zenodo. Ses métadonnées DataCite donnent la version la plus récente (`v2.14`)."""


def dump_version(archive_name: str) -> str:
    """Version d'une archive du dump : `v2.14` pour `v2.14-2026-10-06-ror-data.zip`."""
    return archive_name.split("-", 1)[0]


def published_ror_version(*, user_agent: str) -> str | None:
    """Version la plus récente du dump, d'après les métadonnées DataCite de son DOI conceptuel. `None` si DataCite ne répond pas."""
    try:
        response = httpx2.get(
            f"{API_BASE_URLS['datacite']}/dois/{ROR_DATA_CONCEPT_DOI}",
            headers={"User-Agent": user_agent},
            timeout=15,
            verify=tls_context(),
        )
        raise_for_status(response)
        attributes = as_mapping(as_mapping(response.json().get("data")).get("attributes"))
    except httpx2.HTTPError, ValueError:
        return None
    return as_str(attributes.get("version"))


@dataclass(frozen=True, slots=True)
class RorDumpFile:
    """Archive d'une version du dump : son nom (`v2.14-2026-10-06-ror-data.zip`…) et son URL de téléchargement."""

    name: str
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
    for file in as_sequence(record.get("files")):
        entry = as_mapping(file)
        name = as_str(entry.get("key")) or ""
        if name.endswith(_ARCHIVE_SUFFIX):
            url = as_str(as_mapping(entry.get("links")).get("self")) or ""
            if httpx2.URL(url).host != ZENODO_HOST:
                raise DumpDownloadError(f"L'archive du dump ROR est hors de {ZENODO_HOST} : {url}")
            return RorDumpFile(name=name, url=url)
    raise DumpDownloadError(
        f"Aucune archive `*{_ARCHIVE_SUFFIX}` dans la dernière version du dump ROR."
    )


def fetch_ror_dump(
    dest_path: str,
    *,
    user_agent: str,
    logger: logging.Logger,
) -> RorDumpFile:
    """Télécharge l'archive de la version la plus récente du dump vers `dest_path`, et la rend."""
    dump = find_latest_ror_dump(user_agent=user_agent)
    download_dump(
        dump.url,
        dest_path,
        label="ROR",
        user_agent=user_agent,
        logger=logger,
        max_bytes=MAX_DUMP_BYTES,
    )
    return dump


def read_ror_dump(archive_path: str) -> Iterator[RorOrganization]:
    """Itère les organisations du CSV de l'archive.

    Lève `ValueError` ou `ValidationError` sur une ligne inexploitable : un dump incomplet laisse le référentiel en place.
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


class ZenodoRorDumpSource:
    """Versions du dump ROR publiées sur Zenodo, et lecture de leurs organisations."""

    def __init__(self, *, user_agent: str, logger: logging.Logger) -> None:
        self._user_agent = user_agent
        self._logger = logger
        self._latest: RorDumpFile | None = None

    def published_version(self) -> str | None:
        """Version la plus récente du dump selon DataCite (`v2.14`), `None` si DataCite ne répond pas."""
        return published_ror_version(user_agent=self._user_agent)

    def latest_version(self) -> str:
        """Nom de l'archive de la version la plus récente. Lève `DumpUnavailableError`."""
        try:
            self._latest = find_latest_ror_dump(user_agent=self._user_agent)
        except _UNAVAILABLE as e:
            raise DumpUnavailableError(str(e)) from e
        return self._latest.name

    def organizations(self, version: str) -> Iterator[RorOrganization]:
        """Organisations de l'archive `version`, téléchargée le temps de la lecture. Lève `DumpUnavailableError`."""
        if self._latest is None or self._latest.name != version:
            raise DumpUnavailableError(f"Version {version} absente de la dernière liste lue.")
        with downloaded_dump(
            self._latest.url,
            file_name=version,
            label="ROR",
            user_agent=self._user_agent,
            logger=self._logger,
            max_bytes=MAX_DUMP_BYTES,
        ) as archive:
            try:
                yield from read_ror_dump(archive)
            except _UNAVAILABLE as e:
                raise DumpUnavailableError(str(e)) from e


_UNAVAILABLE = (
    httpx2.HTTPError,
    DumpDownloadError,
    SourceUnavailableError,
    ValueError,
    ValidationError,
    zipfile.BadZipFile,
)
"""Échecs qui rendent le dump inaccessible : réseau, serveur, archive ou ligne inexploitable."""
