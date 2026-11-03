"""Accès à l'API HAL : recherche Solr des documents (moissonnage, recherche d'un document) et référentiel des structures (`ref/structure`)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

import httpx2

from domain.sources.registry import source_record_url
from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.http_retry import (
    http_get_text_with_retry_async,
    http_request_with_retry,
    lookup_json_async,
)
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, HAL_PER_PAGE
from pipeline.ingestion.hal.structures import HAL_STRUCTURE_FIELDS

type SolrParams = dict[str, str | int | float | bool | None]

HAL_FIELDS = [
    "halId_s",
    "doiId_s",
    "title_s",
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
    # `label_xml` (TEI) : seul champ qui rattache l'ORCID et l'IdRef à chaque auteur par sa position. `authORCIDIdExt_s` et `authIdRefIdExt_s` omettent les valeurs nulles et perdent l'alignement : ils restent hors de la liste.
    "label_xml",
    "producedDateY_i",
    "publicationDate_s",
    "docType_s",
    "docSubType_s",
    "language_s",
    "journalTitle_s",
    "journalIssn_s",
    "journalEissn_s",
    "journalPublisher_s",
    "bookTitle_s",
    "publisher_s",
    "conferenceTitle_s",
    # Publication d'une communication : indicateur « avec actes », collections, titre de la source.
    "proceedings_s",
    "serie_s",
    "source_s",
    "fileMain_s",
    # Annexes déposées (URL) : diaporama, poster, matériel supplémentaire. Un dépôt peut avoir des annexes sans fichier principal.
    "fileAnnexes_s",
    # Licence du fichier déposé (URL), présente quand un fichier est déposé.
    "licence_s",
    "linkExtUrl_s",
    "uri_s",
    "label_s",
    "collCode_s",
    "nntId_s",
    "pubmedId_s",
    "abstract_s",
    # Domaines CCSD : `<code>_FacetSep_<libellé racine>/…/<libellé feuille>`, avec le libellé de chaque niveau. `domain_s` donne seulement les codes.
    "fr_domainAllCodeLabel_fs",
    "volume_s",
    "issue_s",
    "page_s",
]
"""Champs Solr demandés : un champ absent de la liste manque aux documents reçus."""

HAL_FIELDS_STR = ",".join(HAL_FIELDS)


class HalClient:
    """Client de l'API de recherche HAL (Solr)."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url.rstrip('/')}/"

    def _get(self, params: SolrParams, label: str) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
        )

    def count(self, query: str, fq: str) -> int:
        """Renvoie le nombre de documents d'une requête, lu sur une réponse sans document (`rows=0`)."""
        params: SolrParams = {"q": query, "fq": fq, "rows": 0, "wt": "json"}
        return as_int(at_path(self._get(params, "HAL comptage"), "response").get("numFound")) or 0

    def fetch_page_cursor(self, query: str, fq: str, cursor_mark: str) -> Mapping[str, JsonValue]:
        """Renvoie une page en pagination `cursorMark`, avec tous les champs de `HAL_FIELDS`.

        `cursor_mark` vaut `"*"` au premier appel, puis le `nextCursorMark` de la réponse précédente. `sort=docid asc`, clé unique, est requis par `cursorMark`.
        """
        params: SolrParams = {
            "q": query,
            "fq": fq,
            "fl": ",".join(HAL_FIELDS),
            "rows": HAL_PER_PAGE,
            "sort": "docid asc",
            "cursorMark": cursor_mark,
            "wt": "json",
        }
        return self._get(params, f"HAL cursor={cursor_mark[:16]}")


async def search_one(
    client: httpx2.AsyncClient, query: str, *, label: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le premier document de la recherche Solr `query`, ou `NOT_FOUND` quand la réponse est vide."""
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["hal"],
        params={"q": query, "fl": HAL_FIELDS_STR, "wt": "json", "rows": "1"},
        timeout=15,
        not_found_statuses=frozenset(),
        label=label,
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    docs = as_sequence(at_path(outcome, "response").get("docs"))
    return as_mapping(docs[0]) if docs else NOT_FOUND


async def find_deposit(
    client: httpx2.AsyncClient, hal_id: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le dépôt HAL `hal_id`, ou le dépôt conservé qui l'a absorbé comme doublon (`halIdSameAs_s`).

    Un dépôt supprimé sort de l'index de recherche. Une recherche vide se confirme donc sur la page du dépôt : `NOT_FOUND` pour une page absente (404). Une page présente donne `UNAVAILABLE` : le dépôt est relu plus tard.
    """
    label = f"halId {hal_id}"
    doc = await search_one(client, f"halId_s:{hal_id} OR halIdSameAs_s:{hal_id}", label=label)
    if not isinstance(doc, NotFound):
        return doc
    try:
        await http_get_text_with_retry_async(
            client, source_record_url("hal", hal_id), timeout=15, label=f"page {hal_id}"
        )
    except httpx2.HTTPStatusError as e:
        return NOT_FOUND if e.response.status_code == 404 else UNAVAILABLE
    except SourceUnavailableError:
        return UNAVAILABLE
    return UNAVAILABLE


HAL_STRUCTURES_BATCH = 100
"""Identifiants par requête : la requête Solr reste courte, et la réponse tient en une page."""


class HalStructuresClient:
    """Client de `ref/structure`."""

    def __init__(self, base_url: str = API_BASE_URLS["hal_structures"]) -> None:
        self._url = base_url

    def _docs(self, field: str, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]:
        params: dict[str, str | int] = {
            "q": f"{field}:({' OR '.join(str(i) for i in sorted(ids))})",
            "fl": ",".join(HAL_STRUCTURE_FIELDS),
            "rows": len(ids) * 2,
            "wt": "json",
        }
        data = http_request_with_retry(
            "GET", self._url, params=params, label=f"HAL structures {field} ×{len(ids)}"
        )
        return [
            as_mapping(d) for d in as_sequence(at_path(as_mapping(data), "response").get("docs"))
        ]

    def by_ids(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]:
        """Renvoie les structures de ces identifiants. Un alias est absent de la réponse."""
        return self._docs("docid", ids)

    def by_aliases(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]:
        """Renvoie les structures conservées avec l'un des `ids` parmi leurs alias."""
        return self._docs("aliasDocid_i", ids)
