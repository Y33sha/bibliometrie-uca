"""Client Sudoc : correspondance ISSN → PPN (service `issn2ppn`) et notices MARCXML des publications en série.

Les requêtes passent par `http_retry`, sur un client asynchrone partagé : nouvelles tentatives, backoff et circuit-breaker de la source. La lecture des notices est définie dans `sudoc_record`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import defusedxml.ElementTree as ET
import httpx2
from defusedxml.common import DefusedXmlException

from domain.documents.identifiers import ISSN
from domain.sources.sudoc import SudocSerialRecord
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import (
    http_get_text_with_retry_async,
    http_request_with_retry_async,
)
from pipeline.ingestion.api_params import SUDOC_ISSN2PPN_BATCH
from pipeline.ingestion.complements.sudoc_record import (
    NotMarcRecordError,
    marc_fields,
    parse_sudoc_serial_record,
)

logger = logging.getLogger(__name__)


def _is_not_found(exc: httpx2.HTTPStatusError) -> bool:
    return exc.response.status_code == 404


def _entries(value: JsonValue) -> list[JsonValue]:
    """Renvoie les entrées d'une clé de réponse `issn2ppn` : une liste, un objet seul ou rien."""
    if value is None:
        return []
    return list(as_sequence(value)) if isinstance(value, list) else [value]


async def fetch_ppns(
    client: httpx2.AsyncClient, issns: Sequence[str], *, base_url: str
) -> dict[str, tuple[str, ...]]:
    """Renvoie les PPN des notices Sudoc de chaque ISSN, interrogés par lots de `SUDOC_ISSN2PPN_BATCH`. Un ISSN sans notice est absent du résultat.

    Le service range les PPN sous `result` pour les notices avec exemplaires en bibliothèque, sous `resultNoHolding` pour les autres. Les deux sont lus.
    """
    result: dict[str, tuple[str, ...]] = {}
    for i in range(0, len(issns), SUDOC_ISSN2PPN_BATCH):
        batch = issns[i : i + SUDOC_ISSN2PPN_BATCH]
        # Le format de réponse se donne dans le chemin : en paramètre de requête, il est ignoré.
        url = f"{base_url}/services/issn2ppn/{','.join(batch)}&format=text/json"
        try:
            data = as_mapping(
                await http_request_with_retry_async(client, "GET", url, label="issn2ppn")
            )
        except httpx2.HTTPStatusError as exc:
            if not _is_not_found(exc):
                raise
            data = {}  # aucun ISSN du lot n'a de notice
        entries = data.get("sudoc")
        for entry in as_sequence(entries) if isinstance(entries, list) else [entries]:
            query = as_mapping(as_mapping(entry).get("query"))
            issn = ISSN.try_parse(as_str(query.get("issn")))
            ppns = tuple(
                ppn
                for key in ("result", "resultNoHolding")
                for r in _entries(query.get(key))
                if (ppn := as_str(as_mapping(r).get("ppn")))
            )
            if issn is not None and ppns:
                result[str(issn)] = ppns
    return result


async def fetch_serial_record(
    client: httpx2.AsyncClient, ppn: str, *, base_url: str
) -> SudocSerialRecord | None:
    """Renvoie la notice Sudoc d'une publication en série, ou `None` si le PPN est inconnu ou la notice illisible.

    La notice vient de l'export `{ppn}.abes.xml`, qui sert aussi les notices sans exemplaire en bibliothèque.
    """
    try:
        xml = await http_get_text_with_retry_async(
            client, f"{base_url}/{ppn}.abes.xml", label=f"notice {ppn}"
        )
    except httpx2.HTTPStatusError as exc:
        if _is_not_found(exc):
            return None
        raise
    try:
        fields = marc_fields(xml)
    except (ET.ParseError, DefusedXmlException, NotMarcRecordError) as exc:
        logger.warning("Notice Sudoc %s illisible : %r", ppn, exc)
        return None
    return parse_sudoc_serial_record(ppn, fields)
