"""Port JournalRepository — édition dans l'administration et fusion de l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). Les deux agrégats sont liés par `journals.publisher_id` (FK) mais manipulés par des opérations distinctes — séparer les ports réduit la surface sur laquelle chaque call site s'engage.

La méthode `find_shared_title_journal_pairs` vit ici : c'est une query sur la table `journals`, appelée par le service de fusion d'éditeurs pour détecter les conflits avant `merge_publisher_into`.
"""

from typing import Protocol, TypedDict

from pydantic import BaseModel

from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from domain.journals.journal import Journal, JournalType, OaModel


class SharedTitleJournalPair(TypedDict):
    """Paire de revues homonymes entre deux éditeurs, et leurs identifiants normalisés.

    Rendue par `find_shared_title_journal_pairs` : chaque ligne contient les deux revues et leurs ISSN. Le service détecte ainsi en une passe les conflits qui empêchent une fusion.
    """

    target_journal_id: int
    target_title: str
    source_journal_id: int
    source_title: str
    t_title: str
    s_title: str
    t_issns: list[JournalIssn]
    s_issns: list[JournalIssn]


class JournalIssnInput(BaseModel):
    """Un ISSN d'une revue, saisi à l'administration."""

    issn: str
    support: IssnSupport | None = None
    linking: bool = False
    status: IssnStatus = IssnStatus.ACTIVE
    replaced_by: str | None = None


class JournalUpdate(BaseModel):
    """Champs éditables d'une revue, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `title_normalized`, dérivé de `title`, est posé par le repository.

    `journal_type` et `oa_model` ont les types du domaine, que les enums SQL des mêmes noms reprennent. Leurs valeurs se vérifient ici.
    """

    title: str | None = None
    issns: list[JournalIssnInput] | None = None
    oa_model: OaModel | None = None
    journal_type: JournalType | None = None
    is_academic: bool | None = None
    apc_amount: float | None = None


class JournalRepository(Protocol):
    """Contrat d'édition dans l'administration et de fusion de l'agrégat Journal."""

    def find_by_id(self, journal_id: int) -> Journal | None:
        """Hydrate l'aggregate `Journal` complet. Retourne None si le journal n'existe pas. Les `journal_name_forms` restent une projection séparée, hors de l'aggregate."""
        ...

    def save(self, journal: Journal) -> None:
        """Persiste une revue chargée : UPDATE de ses champs éditables par l'API. `title_normalized` est re-dérivé du titre ; les colonnes gérées par le pipeline ne sont pas touchées. Lève `NotFoundError` si l'id est absent."""
        ...

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitleJournalPair]:
        """Paires de revues (une du `target_publisher_id`, une du `source_publisher_id`) partageant le même `title_normalized`. Chaque ligne contient `target_journal_id`, `source_journal_id` et les six valeurs ISSN/eISSN/ISSN-L des deux côtés. Le service détecte ainsi les conflits d'ISSN en une seule requête."""
        ...

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id` : applique la règle de fusion de chaque donnée de la revue (`domain.journals.merge.JOURNAL_DATA`), supprime la source, puis recalcule les compteurs de publications."""
        ...
