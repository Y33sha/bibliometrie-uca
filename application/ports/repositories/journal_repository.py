"""Port JournalRepository — contrat d'accès à l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP).
Les deux agrégats sont liés par `journals.publisher_id` (FK) mais
manipulés par des opérations distinctes — séparer les ports réduit la
surface sur laquelle chaque call site s'engage.

La méthode `find_shared_title_journal_pairs` reste ici : c'est une
query sur la table `journals`, appelée par le service de fusion
d'éditeurs pour détecter les conflits avant `merge_publisher_into`.

Implémenté par `infrastructure/repositories/journal_repository.py`.
"""

from datetime import datetime
from typing import Any, Protocol, TypedDict

from domain.journals.journal import Journal


class JournalUpdateFields(TypedDict, total=False):
    """Partial update sur la table `journals`.

    Toutes les clés sont optionnelles (`total=False`) ; le repo applique
    un UPDATE sur les clés effectivement présentes. `title_normalized`
    est calculé par le service quand `title` est fourni.
    """

    title: str
    title_normalized: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    doi_prefix: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    is_predatory: bool | None
    is_in_doaj: bool | None
    apc_amount: float | None


class JournalRepository(Protocol):
    """Contrat d'accès à l'agrégat Journal."""

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, journal_id: int) -> Journal | None:
        """Hydrate l'aggregate `Journal` complet. Retourne None si le
        journal n'existe pas. Les `journal_name_forms` ne sont pas
        chargées par l'aggregate (projection séparée — voir
        `find_journal_by_name_form` pour les lookups par forme)."""
        ...

    # ── journal_name_forms ─────────────────────────────────────────

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None: ...

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None: ...

    # ── journals ───────────────────────────────────────────────────

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_journal_by_issn_any(self, issn_value: str) -> int | None: ...

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: str | None = None,
    ) -> None: ...

    def create_journal(
        self,
        *,
        title: str,
        title_normalized: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: str | None,
    ) -> int: ...

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool: ...

    def update_journal_fields(self, journal_id: int, fields: JournalUpdateFields) -> None: ...

    # ── APC / DOAJ ─────────────────────────────────────────────────

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None: ...

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: dict[str, Any] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        """Pose `doaj_payload`, `doaj_imported_at` et `is_in_doaj` en bloc.

        Utilisé par l'import du dump DOAJ (`import_journals_from_doaj_dump`) pour
        les revues matchées (`is_in_doaj=True` + payload). Le cas « absente du
        dump » est traité en bloc par `reset_is_in_doaj` (FALSE global avant
        re-pose).
        """
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict[str, Any]]: ...

    def merge_journal_into(self, target_id: int, source_id: int) -> None: ...
