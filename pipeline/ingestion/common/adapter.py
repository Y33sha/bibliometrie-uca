"""Adaptateur d'une source : les implémentations que les phases câblent pour elle.

Chaque source expose le sien dans son paquet (`pipeline/ingestion/<source>/__init__.py`), et `pipeline.ingestion.adapters` les réunit. L'adaptateur implémente le profil de la source (`domain.sources.registry.SourceProfile`) : un moissonneur si elle est moissonnée, une recherche par DOI si elle s'interroge par DOI, un moissonneur par personne si elle cherche des identifiants de personne.

Chaque fabrique importe le code de la source au moment où elle s'exécute. Une source écartée du run ne charge donc pas son code, et `common.staging`, que les modules des sources importent, lit l'empreinte dans l'adaptateur sans les importer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from domain.types import JsonValue

if TYPE_CHECKING:
    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.harvester import HarvesterFactory
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import StaleRefetch

type StripVolatile = Callable[[Mapping[str, JsonValue]], Mapping[str, JsonValue]]
"""Copie d'un payload sans son bruit volatil, sur laquelle se calcule l'empreinte de détection de changement."""


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    """Identifiant natif d'un document dans sa source, et ses DOI nettoyés."""

    source_id: str
    dois: tuple[str, ...] = ()

    @classmethod
    def of(cls, source_id: str, *dois: str | None) -> RecordIdentity:
        """Identité de `source_id`, avec les DOI non vides de `dois`, sans doublon."""
        return cls(source_id, tuple(dict.fromkeys(d for d in dois if d)))

    @property
    def doi(self) -> str | None:
        """DOI principal du document : le premier de ses DOI."""
        return self.dois[0] if self.dois else None


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    source: Source
    # Identité d'un document reçu de la source, ou `None` pour un document sans identifiant.
    identify: Callable[[Mapping[str, JsonValue]], RecordIdentity | None]
    # Nouvelle lecture des documents par identifiant natif (phase `fetch_stale`).
    stale_refetch: Callable[[], StaleRefetch]
    # Classe du normaliseur, que la phase `normalize` construit sur ses stores.
    normalizer: Callable[[], type[SourceNormalizer]]
    # Moissonnage sur les critères d'affiliation du périmètre (phase `harvest`). Le client de l'API se construit avec le moissonneur.
    harvester: HarvesterFactory | None = None
    # Moissonnage par identifiant de personne (phase `harvest_by_person`).
    person_harvester: HarvesterFactory | None = None
    # Recherche par DOI (phase `fetch_missing`).
    doi_search: Callable[[], DoiSearch] | None = None
    # Neutralisation du bruit volatil avant l'empreinte. `None` : l'empreinte porte sur le payload fidèle.
    strip_volatile: StripVolatile | None = None
    # Vrai quand un document reçu d'une réponse de liste atteint le plafond d'auteurs de la source : sa liste est peut-être tronquée. `None` : la source ne plafonne pas.
    authors_truncated: Callable[[Mapping[str, JsonValue]], bool] | None = None
