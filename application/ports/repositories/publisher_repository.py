"""Port PublisherRepository — édition, enrichissement pays et fusion de l'agrégat Publisher.

Séparé de `JournalRepository` (principe ISP) : publishers et journals sont deux agrégats distincts, bien que liés par une FK. Un appelant limité aux publishers s'engage sur le seul contrat éditeurs, et inversement.

La fusion d'éditeurs (`merge_publisher_into`) vit ici : sémantiquement c'est une opération atomique sur un éditeur qui touche par effet de bord les tables liées (`infrastructure/repositories/publisher_merge.py`). La détection des journaux à conflit avant fusion est exposée par `JournalRepository.find_shared_title_journal_pairs`, une query sur `journals`.
"""

from typing import Protocol

from pydantic import BaseModel, field_validator

from domain.publishers.publisher import Publisher, PublisherType


class PublisherUpdate(BaseModel):
    """Champs éditables d'un éditeur, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `name_normalized`, dérivé de `name`, est posé par le repository.
    """

    name: str | None = None
    country: str | None = None
    publisher_type: PublisherType | None = None

    @field_validator("country")
    @classmethod
    def _country_lowercase(cls, v: str | None) -> str | None:
        # Code pays en minuscule (cf. countries.code / addresses.countries).
        return v.lower() if v else v


class PublisherRepository(Protocol):
    """Contrat d'édition, d'enrichissement pays et de fusion de l'agrégat Publisher."""

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, publisher_id: int) -> Publisher | None:
        """Hydrate l'aggregate `Publisher` complet. Retourne None si l'éditeur n'existe pas. Les `publisher_name_forms` restent une projection séparée, hors de l'aggregate."""
        ...

    # ── Enrichissement pays (maintenance) ──────────────────────────

    # ── Persistance de l'agrégat ───────────────────────────────────

    def save(self, publisher: Publisher) -> None:
        """Persiste un éditeur chargé : UPDATE de ses champs éditables par l'API. `name_normalized` est re-dérivé du nom ; les colonnes gérées par le pipeline ne sont pas touchées. Lève `NotFoundError` si l'id est absent."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def crossref_member_ids(self, publisher_id: int) -> tuple[int, ...]:
        """Membres Crossref de l'éditeur, tirés de ses préfixes DOI."""
        ...

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        """Fusionne l'éditeur `source_id` dans `target_id` : applique la règle de fusion de chaque donnée de l'éditeur, puis supprime la source. La fusion préalable des revues homonymes relève du service via `find_shared_title_journal_pairs`."""
        ...
