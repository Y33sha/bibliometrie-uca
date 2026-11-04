"""Contrats d'une source : lecture des documents reçus (`PayloadReader`), implémentations câblées par les phases (`SourceAdapter`).

Chaque source expose son lecteur dans son paquet (`pipeline/ingestion/<source>/__init__.py`), chargé à la demande par `pipeline.ingestion.payload_readers`. Le lecteur dépend seulement des champs des documents : les modules communs bas niveau, comme `staging`, le lisent sans importer le reste du code des sources.

Chaque source expose son adaptateur dans `pipeline/ingestion/<source>/adapter.py`, chargé à la demande par `pipeline.ingestion.adapters`, importé par les phases. L'adaptateur implémente le profil de la source (`domain.sources.registry.SourceProfile`) : un moissonneur si elle est moissonnée, une recherche par DOI si elle s'interroge par DOI, un moissonneur par personne si elle cherche des identifiants de personne.
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
    from pipeline.ingestion.common.stale_refetch import FetchOne

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
class PayloadReader:
    """Lecture des documents reçus d'une source."""

    source: Source
    identify: Callable[[Mapping[str, JsonValue]], RecordIdentity | None]
    """Renvoie l'identifiant natif et les DOI d'un document reçu de la source, ou `None` pour un document sans identifiant."""
    strip_volatile: StripVolatile | None = None
    """Neutralisation du bruit volatil avant l'empreinte. `None` : l'empreinte se calcule sur le payload tel quel."""
    authors_truncated: Callable[[Mapping[str, JsonValue]], bool] | None = None
    """Renvoie vrai quand un document reçu d'une réponse de liste atteint le plafond d'auteurs de la source : sa liste est peut-être tronquée. `None` : la source ne plafonne pas."""


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    """Implémentations d'une source, câblées par les phases."""

    source: Source
    fetch_by_native_id: FetchOne
    """Lecture d'un document par son identifiant natif (phase `fetch_stale`)."""
    normalizer: type[SourceNormalizer]
    """Classe du normaliseur, construite par la phase `normalize` sur ses stores."""
    harvester: HarvesterFactory | None = None
    """Moissonnage sur les critères d'affiliation du périmètre (phase `harvest`). Le client de l'API se construit avec le moissonneur."""
    person_harvester: HarvesterFactory | None = None
    """Moissonnage par identifiant de personne (phase `harvest_by_person`)."""
    doi_search: DoiSearch | None = None
    """Recherche par DOI (phase `fetch_missing`)."""
