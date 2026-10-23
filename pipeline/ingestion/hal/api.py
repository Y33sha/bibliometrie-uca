"""Accès à l'API HAL : recherche Solr des documents (moissonnage, recherche d'un document) et référentiel des structures (`ref/structure`)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

import httpx2

from domain.structures.hal_structures import HAL_STRUCTURE_FIELDS
from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, HAL_PER_PAGE

type SolrParams = dict[str, str | int | float | bool | None]

# Champs Solr demandés : un champ absent de la liste manque aux enregistrements reçus.
HAL_FIELDS = [
    "halId_s",
    "doiId_s",
    "title_s",
    "subTitle_s",
    "authFullNameFormIDPersonIDIDHal_fs",
    "authQuality_s",
    # label_xml (TEI) : seul champ qui attache ORCID/IdRef à chaque auteur
    # par position. Les listes `authORCIDIdExt_s` / `authIdRefIdExt_s`
    # sont compactées (valeurs non-null seulement, pas d'alignement) et
    # ne sont donc pas demandées.
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
    "openAccess_bool",
    "fileMain_s",
    # Licence du fichier déposé (URL), présente quand un fichier est déposé.
    "licence_s",
    "linkExtId_s",
    "linkExtUrl_s",
    "uri_s",
    "label_s",
    "collCode_s",
    "nntId_s",
    "pubmedid_s",
    "abstract_s",
    "keyword_s",
    # Domaines CCSD : `<code>_FacetSep_<libellé racine>/…/<libellé feuille>`, qui
    # porte le libellé de chaque niveau. `domain_s` n'expose que les codes.
    "fr_domainAllCodeLabel_fs",
    "volume_s",
    "issue_s",
    "page_s",
]

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
        """Nombre de documents d'une requête, lu sur une réponse sans document (`rows=0`)."""
        params: SolrParams = {"q": query, "fq": fq, "rows": 0, "wt": "json"}
        return as_int(at_path(self._get(params, "HAL comptage"), "response").get("numFound")) or 0

    def fetch_page_cursor(self, query: str, fq: str, cursor_mark: str) -> Mapping[str, JsonValue]:
        """Une page en pagination `cursorMark`, avec tous les champs de `HAL_FIELDS`.

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
    """Premier document de la recherche Solr `query`, ou `NOT_FOUND` quand la réponse est vide."""
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


# Identifiants par requête : la requête Solr reste courte, et la réponse tient en une page.
HAL_STRUCTURES_BATCH = 100


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
        """Structures d'identifiants `ids`. Un alias est absent de la réponse."""
        return self._docs("docid", ids)

    def by_aliases(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]:
        """Structures conservées qui listent un des `ids` dans leurs alias."""
        return self._docs("aliasDocid_i", ids)
