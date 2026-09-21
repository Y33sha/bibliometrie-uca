"""Port d'accès pipeline à la table `monographs`, servi par `PgMonographGatewayQueries` (`infrastructure/pipeline/monographs.py`)."""

from typing import NamedTuple, Protocol


class MonographMatch(NamedTuple):
    """Une monographie trouvée, avec ses ISBN et son éditeur."""

    id: int
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None


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

    def find_monographs_by_title(
        self, title_normalized: str, publisher_id: int | None
    ) -> list[MonographMatch]:
        """Les monographies de ce titre normalisé, par `id` : celles de cet éditeur et celles sans éditeur. Sans éditeur, toutes les monographies de ce titre."""
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
