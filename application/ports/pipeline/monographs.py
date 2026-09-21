"""Port d'accès pipeline à la table `monographs`, servi par `PgMonographGatewayQueries` (`infrastructure/pipeline/monographs.py`)."""

from typing import NamedTuple, Protocol

from domain.monographs.matching import MonographCandidate


class MonographTitleGroup(NamedTuple):
    """Monographies qui partagent un titre normalisé, avec le titre de la plus ancienne."""

    title: str
    monographs: tuple[MonographCandidate, ...]


class MonographMergeQueries(Protocol):
    """Fusion des monographies en double."""

    def find_monographs_sharing_a_title(self) -> list[MonographTitleGroup]:
        """Groupes d'au moins deux monographies de même titre normalisé."""
        ...

    def merge_monograph_into(self, target_id: int, source_id: int) -> None:
        """Reporte sur `target_id` les enregistrements et les publications de `source_id`, complète les champs vides de la cible, puis supprime la source."""
        ...


class MonographJournalCandidates(NamedTuple):
    """Une monographie, son `journal_id`, et les entrées de `journals` que portent ses enregistrements, à ISSN et sans ISSN."""

    monograph_id: int
    title: str
    journal_id: int | None
    with_issn: tuple[int, ...]
    without_issn: tuple[int, ...]


class MonographCollectionQueries(Protocol):
    """Rattachement des monographies à leur collection."""

    def find_monograph_journal_candidates(self) -> list[MonographJournalCandidates]:
        """Chaque monographie portée par au moins un enregistrement, avec les entrées de `journals` de ses enregistrements."""
        ...

    def set_monograph_journal(self, monograph_id: int, journal_id: int | None) -> None:
        """Pose le `journal_id` d'une monographie."""
        ...


class MonographCleanupQueries(Protocol):
    """Suppression des monographies vides."""

    def delete_empty_monographs(self) -> list[tuple[int, str]]:
        """Supprime les monographies qu'aucun enregistrement ni aucune publication ne porte, et rend `(id, titre)` de chacune."""
        ...


class MonographFindOrCreateQueries(Protocol):
    """Trouve ou crée une monographie à partir des métadonnées d'une source (consommé par les normaliseurs)."""

    def find_monograph_by_isbn(self, isbn: str) -> int | None:
        """La monographie qui porte `isbn` dans `isbn` ou `eisbn`."""
        ...

    def find_monographs_by_title(self, title_normalized: str) -> list[MonographCandidate]:
        """Les monographies de ce titre normalisé, par `id`."""
        ...

    def create_monograph(
        self,
        *,
        title: str,
        title_normalized: str,
        proceedings: bool,
        year: int | None,
        isbn: str | None,
        eisbn: str | None,
        publisher_id: int | None,
        journal_id: int | None,
    ) -> int:
        """Insère une monographie et retourne son `id`."""
        ...

    def enrich_monograph(
        self,
        monograph_id: int,
        *,
        proceedings: bool,
        year: int | None,
        isbn: str | None,
        eisbn: str | None,
        publisher_id: int | None,
        journal_id: int | None,
    ) -> None:
        """Complète les champs vides d'une monographie. Un ISBN déjà porté par une autre monographie reste hors de ses colonnes. `proceedings` vrai fait d'un livre un volume d'actes."""
        ...
