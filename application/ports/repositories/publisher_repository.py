"""Port PublisherRepository — édition, enrichissement pays et fusion de l'agrégat Publisher.

Séparé de `JournalRepository` (principe ISP) : publishers et journals sont deux agrégats distincts, bien que liés par une FK. Un appelant limité aux publishers s'engage sur le seul contrat éditeurs, et inversement.

Le trouve-ou-crée, alimenté par le pipeline, vit à part dans `application/ports/pipeline/publishers.py`.

La fusion d'éditeurs (`merge_publisher_into`) vit ici : sémantiquement c'est une opération atomique sur un éditeur qui touche par effet de bord les tables liées (`journals.publisher_id`, `publisher_name_forms`, `journal_name_forms.publisher_id`, `apc_payments.publisher_id`). La détection des journaux à conflit avant fusion est exposée par `JournalRepository.find_shared_title_journal_pairs`, une query sur `journals`.
"""

from typing import Protocol

from pydantic import BaseModel, field_validator


class PublisherUpdate(BaseModel):
    """Champs éditables d'un éditeur, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `name_normalized`, dérivé de `name`, est posé par le repository.
    """

    name: str | None = None
    country: str | None = None
    publisher_type: str | None = None

    @field_validator("country")
    @classmethod
    def _country_lowercase(cls, v: str | None) -> str | None:
        # Code pays canonique en minuscule (cf. countries.code / addresses.countries).
        return v.lower() if v else v


class PublisherRepository(Protocol):
    """Contrat d'édition, d'enrichissement pays et de fusion de l'agrégat Publisher."""

    # ── Lecture de commande ────────────────────────────────────────

    def exists(self, publisher_id: int) -> bool:
        """Vrai si l'éditeur existe. Garde-fou d'existence avant fusion, sans hydrater l'agrégat."""
        ...

    # ── Enrichissement pays (maintenance) ──────────────────────────

    def find_needing_country_enrichment(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des éditeurs à `openalex_id` connu et `country` absent, triés par id (batching stable). `limit=None` les rend tous."""
        ...

    # ── Édition sélective ──────────────────────────────────────────

    def update_publisher_fields(self, publisher_id: int, fields: PublisherUpdate) -> None:
        """Applique une modification sélective (`PublisherUpdate`) ; le service garantit au moins un champ fourni. `name_normalized` est re-dérivé quand `name` est présent. Lève `NotFoundError` si l'éditeur est introuvable."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        """Fusionne l'éditeur `source_id` dans `target_id` : transfère journaux, formes de nom et paiements APC, enrichit la cible par COALESCE, puis supprime la source. La fusion préalable des journaux à titre partagé relève du service via `find_shared_title_journal_pairs`."""
        ...
