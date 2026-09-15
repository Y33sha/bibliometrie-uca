"""Ports d'accès pipeline à la table `journals`.

Des contrats étroits, un par consommateur du pipeline, tous servis par un même adapter `PgJournalGatewayQueries` (la table est mono-adapter, cf. `infrastructure/pipeline/journals.py`) :

- `JournalFindOrCreateQueries` : lookup + création + enrichissement à la création, pour `find_or_create_journal` (appelé par les normaliseurs de sources) ;
- `JournalOpenAlexEnrichmentQueries` : file des revues à typer + écriture APC / journal_type, pour l'enrichissement OpenAlex ;
- `JournalSudocQueries` : file des revues à vérifier + écriture des ISSN vérifiés, pour la vérification dans le Sudoc ;
- `JournalDoajQueries` : index ISSN + drapeau `is_in_doaj`, pour l'import du dump DOAJ.

L'édition dans l'administration et la fusion ont leur propre port, `application/ports/repositories/journal_repository.py`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple, Protocol

from domain.journals.journal import JournalType, OaModel
from domain.types import JsonValue


class JournalIssnRow(NamedTuple):
    """Une revue indexable par ISSN : son `id` et ses trois formes d'ISSN (au moins une non-nulle)."""

    id: int
    issn: str | None
    eissn: str | None
    issnl: str | None


class JournalFindOrCreateQueries(Protocol):
    """Trouve ou crée une revue à partir des métadonnées d'une source (consommé par les normaliseurs)."""

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        """Ajoute une forme de nom normalisée pour une revue, si absente (idempotent). No-op si `form_normalized` est vide."""
        ...

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Cherche un `journal_id` par forme de nom normalisée. En cas d'ambiguïté, privilégie les revues à eISSN. `publisher_id` fourni : restreint aux formes de cet éditeur ou sans éditeur."""
        ...

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche une revue dont l'un des trois champs ISSN (`issn`, `eissn`, `issnl`) vaut `issn_value`."""
        ...

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        """Complète une revue existante avec les champs non nuls fournis, en COALESCE par champ : une valeur déjà en place est conservée.

        Un ISSN que la revue porte déjà, dans l'une des trois colonnes, n'est pas réécrit dans une autre. Un ISSN nouveau remet la revue à vérifier dans le Sudoc.
        """
        ...

    def add_rejected_issns(self, journal_id: int, values: Sequence[str]) -> None:
        """Ajoute des ISSN invalides à `rejected_issns` de la revue, sans doublon. Une valeur nouvelle remet la revue à vérifier dans le Sudoc."""
        ...

    def create_journal(
        self,
        *,
        title: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère une revue et retourne son `id`. `title_normalized` est dérivé de `title`."""
        ...


class JournalOpenAlexEnrichmentQueries(Protocol):
    """Enrichit les revues depuis OpenAlex Sources : typage des revues indéterminées et écriture APC."""

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des revues au `journal_type` indéterminé qui portent un `openalex_id`, à typer via OpenAlex. Le type étant stable par revue, une revue typée sort de la file. `limit` cape le run."""
        ...

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None:
        """Met à jour le montant et la devise d'APC. COALESCE : un argument `None` laisse la valeur en place."""
        ...

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue. Écriture directe, sans requalification des publications — c'est l'édition admin, elle, qui rejoue les corrections de `doc_type`."""
        ...


class JournalSudocRow(NamedTuple):
    """Une revue à vérifier dans le Sudoc : son titre, ses trois formes d'ISSN et ses ISSN rejetés."""

    id: int
    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    rejected_issns: tuple[str, ...]


class JournalSudocQueries(Protocol):
    """Vérification des ISSN des revues dans le Sudoc."""

    def find_journals_to_check_in_sudoc(self) -> list[JournalSudocRow]:
        """Revues jamais vérifiées dans le Sudoc (`sudoc_checked_at` nul) qui portent au moins un ISSN, valide ou rejeté."""
        ...

    def record_sudoc_check(
        self,
        journal_id: int,
        *,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        rejected_issns: Sequence[str],
        checked_at: datetime,
    ) -> None:
        """Écrit les ISSN vérifiés d'une revue et la date de vérification."""
        ...


class JournalDoajQueries(Protocol):
    """Import du dump DOAJ : index ISSN des revues et pose du drapeau `is_in_doaj`."""

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        """Les revues portant au moins un ISSN — matière de l'index ISSN → revue à l'import du dump DOAJ."""
        ...

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: Mapping[str, JsonValue] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        """Pose `doaj_payload`, `doaj_imported_at` et `is_in_doaj` en bloc.

        Utilisé par l'import du dump DOAJ pour les revues matchées (`is_in_doaj=True` + payload). Le cas « absente du dump » est traité en bloc par `reset_is_in_doaj` (FALSE global avant re-pose).
        """
        ...

    def reset_is_in_doaj(self) -> int:
        """Efface le drapeau `is_in_doaj` de toutes les revues qui le portent, le dump DOAJ faisant autorité — l'import le re-pose ensuite sur les revues matchées. Retourne le nombre de drapeaux effacés."""
        ...

    def doaj_last_import_at(self) -> datetime | None:
        """Date du dernier import DOAJ (`max(doaj_imported_at)`), `None` si jamais importé. Commande la staleness du téléchargement du dump."""
        ...
