"""Client du référentiel des structures HAL (`ref/structure`), interrogé par lots d'identifiants."""

from collections.abc import Collection, Mapping, Sequence

from domain.structures.hal_structures import HAL_STRUCTURE_FIELDS
from domain.types import JsonValue, as_mapping, as_sequence, at_path
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.throttle import Throttle
from pipeline.ingestion.api_params import API_BASE_URLS, HAL_DELAY

# Identifiants par requête : la requête Solr reste courte, et la réponse tient en une page.
HAL_STRUCTURES_BATCH = 100


class HalStructuresClient:
    """Client de `ref/structure`, limité à un appel toutes les `HAL_DELAY` secondes."""

    def __init__(self, base_url: str = API_BASE_URLS["hal_structures"]) -> None:
        self._url = base_url
        self._throttle = Throttle(HAL_DELAY)

    def _docs(self, field: str, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]:
        params: dict[str, str | int] = {
            "q": f"{field}:({' OR '.join(str(i) for i in sorted(ids))})",
            "fl": ",".join(HAL_STRUCTURE_FIELDS),
            "rows": len(ids) * 2,
            "wt": "json",
        }
        with self._throttle.request():
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
