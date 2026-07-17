"""Port PublisherRepository — contrat d'accès à l'agrégat Publisher.

Séparé de `JournalRepository` (principe ISP) : publishers et journals
sont deux agrégats distincts, bien que liés par une FK. Les pipelines
qui ne créent que des publishers ne dépendent pas du contrat journaux,
et inversement.

La fusion d'éditeurs (`merge_publisher_into`) reste ici : sémantiquement
c'est une opération atomique sur un éditeur qui touche par effet de
bord les tables liées (`journals.publisher_id`, `publisher_name_forms`,
`journal_name_forms.publisher_id`, `apc_payments.publisher_id`).
La détection des journaux à conflit avant fusion est exposée par
`JournalRepository.find_shared_title_journal_pairs` car c'est une
query sur `journals`.

Implémenté par `infrastructure/repositories/publisher_repository.py`.
"""

from typing import Protocol

from pydantic import BaseModel, field_validator

from domain.publishers.publisher import Publisher


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
    """Contrat d'accès à l'agrégat Publisher."""

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, publisher_id: int) -> Publisher | None:
        """Hydrate l'aggregate `Publisher` complet. Retourne None si
        l'éditeur n'existe pas. Les `publisher_name_forms` ne sont pas
        chargées par l'aggregate (projection séparée — voir
        `find_publisher_by_name_form` pour les lookups par forme)."""
        ...

    # ── publisher_name_forms ───────────────────────────────────────

    def add_publisher_name_form(
        self,
        publisher_id: int,
        form_normalized: str,
    ) -> None: ...

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None: ...

    # ── publishers ─────────────────────────────────────────────────

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_needing_country_enrichment(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des éditeurs à `openalex_id` connu et `country` absent, triés par id (batching stable). `limit=None` les rend tous."""
        ...

    def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None: ...

    def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int: ...

    def match_or_create_by_name_form(self, name_raw: str, name_normalized: str) -> tuple[int, bool]:
        """`(id, created)` : l'éditeur dont la forme de nom normalisée existe déjà, sinon un éditeur créé et sa forme enregistrée."""
        ...

    def update_publisher_fields(self, publisher_id: int, fields: PublisherUpdate) -> None: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_publisher_into(self, target_id: int, source_id: int) -> None: ...
