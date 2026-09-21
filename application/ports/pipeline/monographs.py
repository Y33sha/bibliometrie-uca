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


class MonographCollectionLink(NamedTuple):
    """Une monographie rattachée à sa collection, avec l'entrée de `journals` qu'elle désignait avant."""

    monograph_id: int
    title: str
    collection_id: int
    collection_title: str
    previous_id: int | None


class MonographCollectionConflict(NamedTuple):
    """Une monographie dont les enregistrements portent plusieurs entrées de `journals` à ISSN."""

    monograph_id: int
    title: str
    candidate_ids: tuple[int, ...]


class MonographCollectionQueries(Protocol):
    """Rattachement des monographies à leur collection."""

    def link_monographs_to_collections(self) -> list[MonographCollectionLink]:
        """Donne pour `journal_id` à chaque monographie la seule entrée de `journals` à ISSN que portent ses enregistrements. Une monographie sans entrée à ISSN, ou à plusieurs, garde son `journal_id`. Rend les rattachements modifiés."""
        ...

    def find_monograph_collection_conflicts(self) -> list[MonographCollectionConflict]:
        """Les monographies dont les enregistrements portent plusieurs entrées de `journals` à ISSN."""
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
