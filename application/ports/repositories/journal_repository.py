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
from typing import Any, NamedTuple, Protocol

from pydantic import BaseModel

from domain.journals.journal import Journal


class JournalIssnRow(NamedTuple):
    """Une revue indexable par ISSN : son `id` et ses trois formes d'ISSN (au moins une non-nulle)."""

    id: int
    issn: str | None
    eissn: str | None
    issnl: str | None


class JournalUpdate(BaseModel):
    """Champs éditables d'une revue, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `title_normalized`, dérivé de `title`, est posé par le repository.
    """

    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: str | None = None
    journal_type: str | None = None
    is_academic: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None


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

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des revues au `journal_type` indéterminé qui portent un `openalex_id`, à typer via OpenAlex. Le type étant stable par revue, une revue typée sort de la file. `limit` cape le run."""
        ...

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        """Les revues portant au moins un ISSN — matière de l'index ISSN → revue à l'import du dump DOAJ."""
        ...

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
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: str | None,
    ) -> int: ...

    # ── Updates génériques ─────────────────────────────────────────

    def journal_exists(self, journal_id: int) -> bool: ...

    def update_journal_fields(self, journal_id: int, fields: JournalUpdate) -> None: ...

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

    def reset_is_in_doaj(self) -> int:
        """Efface le drapeau `is_in_doaj` de toutes les revues qui le portent, le dump DOAJ faisant autorité — l'import le re-pose ensuite sur les revues matchées. Retourne le nombre de drapeaux effacés."""
        ...

    def doaj_last_import_at(self) -> datetime | None:
        """Date du dernier import DOAJ (`max(doaj_imported_at)`), `None` si jamais importé. Commande la staleness du téléchargement du dump."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict[str, Any]]: ...

    def merge_journal_into(self, target_id: int, source_id: int) -> None: ...
