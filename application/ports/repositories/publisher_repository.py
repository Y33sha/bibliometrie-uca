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

from typing import Protocol, TypedDict

from domain.publishers.publisher import Publisher


class PublisherUpdateFields(TypedDict, total=False):
    """Partial update sur la table `publishers`.

    `name_normalized` est calculé par le service quand `name` est fourni.
    """

    name: str
    name_normalized: str
    country: str | None
    is_predatory: bool | None
    publisher_type: str


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

    def publisher_exists(self, publisher_id: int) -> bool: ...

    def update_publisher_fields(self, publisher_id: int, fields: PublisherUpdateFields) -> None: ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_publisher_into(self, target_id: int, source_id: int) -> None: ...
