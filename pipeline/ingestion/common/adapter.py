"""Adaptateur d'une source : implémentations câblées par les phases.

Chaque source expose le sien dans son paquet (`pipeline/ingestion/<source>/__init__.py`), et `pipeline.ingestion.adapters` les réunit. L'adaptateur implémente le profil de la source (`domain.sources.registry.SourceProfile`) : un moissonneur si elle est moissonnée, une recherche par DOI si elle s'interroge par DOI, un moissonneur par personne si elle cherche des identifiants de personne.

Chaque fabrique importe le code de la source à son exécution. Une source écartée du run ne charge donc pas son code. `common.staging`, importé par les modules des sources, lit l'empreinte dans l'adaptateur sans importer ces modules.
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
        """Construit l'identifiant natif et les DOI non vides du document, sans doublon."""
        return cls(source_id, tuple(dict.fromkeys(d for d in dois if d)))

    @property
    def doi(self) -> str | None:
        """DOI principal du document : le premier de ses DOI."""
        return self.dois[0] if self.dois else None


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    """Implémentations d'une source, câblées par les phases."""

    source: Source
    identify: Callable[[Mapping[str, JsonValue]], RecordIdentity | None]
    """Renvoie l'identifiant natif et les DOI d'un document reçu de la source, ou `None` pour un document sans identifiant."""
    stale_refetch: Callable[[], StaleRefetch]
    """Nouvelle lecture des documents par identifiant natif (phase `fetch_stale`)."""
    normalizer: Callable[[], type[SourceNormalizer]]
    """Classe du normaliseur, construite par la phase `normalize` sur ses stores."""
    harvester: HarvesterFactory | None = None
    """Moissonnage sur les critères d'affiliation du périmètre (phase `harvest`). Le client de l'API se construit avec le moissonneur."""
    person_harvester: HarvesterFactory | None = None
    """Moissonnage par identifiant de personne (phase `harvest_by_person`)."""
    doi_search: Callable[[], DoiSearch] | None = None
    """Recherche par DOI (phase `fetch_missing`)."""
    strip_volatile: StripVolatile | None = None
    """Neutralisation du bruit volatil avant l'empreinte. `None` : l'empreinte se calcule sur le payload tel quel."""
    authors_truncated: Callable[[Mapping[str, JsonValue]], bool] | None = None
    """Renvoie vrai quand un document reçu d'une réponse de liste atteint le plafond d'auteurs de la source : sa liste est peut-être tronquée. `None` : la source ne plafonne pas."""
