"""Client Sudoc : correspondance ISSN → PPN (service `issn2ppn`) et notices MARCXML des publications en série.

Le HTTP passe par les helpers partagés de `http_retry` : retry, backoff et alimentation du circuit-breaker de source. Le XML est lu avec `defusedxml`, qui refuse les déclarations d'entités. L'interprétation des zones de la notice appartient à `domain.sources.sudoc`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import defusedxml.ElementTree as ET
import httpx2
from defusedxml.common import DefusedXmlException

from domain.publications.identifiers import ISSN
from domain.sources.sudoc import MarcField, SudocSerialRecord, parse_sudoc_serial_record
from domain.types import as_mapping, as_sequence, as_str
from infrastructure.sources.api_params import SUDOC_DELAY, SUDOC_ISSN2PPN_BATCH
from infrastructure.sources.http_retry import http_get_text_with_retry, http_request_with_retry

logger = logging.getLogger(__name__)


def _is_not_found(exc: httpx2.HTTPStatusError) -> bool:
    return exc.response.status_code == 404


def fetch_ppns(issns: Sequence[str], *, base_url: str) -> dict[str, tuple[str, ...]]:
    """PPN des notices Sudoc de chaque ISSN, par lots de `SUDOC_ISSN2PPN_BATCH`. Un ISSN sans notice est absent du résultat."""
    result: dict[str, tuple[str, ...]] = {}
    for i in range(0, len(issns), SUDOC_ISSN2PPN_BATCH):
        batch = issns[i : i + SUDOC_ISSN2PPN_BATCH]
        # Le format de réponse se donne dans le chemin : en paramètre de requête, il est ignoré.
        url = f"{base_url}/services/issn2ppn/{','.join(batch)}&format=text/json"
        try:
            data = as_mapping(http_request_with_retry("GET", url, label="issn2ppn"))
        except httpx2.HTTPStatusError as exc:
            if not _is_not_found(exc):
                raise
            data = {}  # aucun ISSN du lot n'a de notice
        entries = data.get("sudoc")
        for entry in as_sequence(entries) if isinstance(entries, list) else [entries]:
            query = as_mapping(as_mapping(entry).get("query"))
            issn = ISSN.try_parse(as_str(query.get("issn")))
            found = query.get("result")
            ppns = tuple(
                ppn
                for r in (as_sequence(found) if isinstance(found, list) else [found])
                if (ppn := as_str(as_mapping(r).get("ppn")))
            )
            if issn is not None and ppns:
                result[str(issn)] = ppns
        time.sleep(SUDOC_DELAY)
    return result


def marc_fields(xml: str) -> list[MarcField]:
    """Zones de données d'une notice MARCXML, dans l'ordre de la notice."""
    root = ET.fromstring(xml)
    fields: list[MarcField] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "datafield":
            continue
        subfields = tuple(
            (sub.get("code") or "", (sub.text or "").strip())
            for sub in element
            if sub.tag.rsplit("}", 1)[-1] == "subfield"
        )
        fields.append(
            MarcField(
                tag=element.get("tag") or "",
                ind1=element.get("ind1") or "",
                ind2=element.get("ind2") or "",
                subfields=subfields,
            )
        )
    return fields


def fetch_serial_record(ppn: str, *, base_url: str) -> SudocSerialRecord | None:
    """Notice Sudoc d'une publication en série, ou `None` si le PPN est inconnu ou la notice illisible."""
    try:
        xml = http_get_text_with_retry(f"{base_url}/{ppn}.xml", label=f"notice {ppn}")
    except httpx2.HTTPStatusError as exc:
        if _is_not_found(exc):
            return None
        raise
    try:
        fields = marc_fields(xml)
    except (ET.ParseError, DefusedXmlException) as exc:
        logger.warning("Notice Sudoc %s illisible : %r", ppn, exc)
        return None
    return parse_sudoc_serial_record(ppn, fields)
