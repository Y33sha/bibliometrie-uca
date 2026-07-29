"""Port JournalRepository — édition et fusion curées de l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). Les deux agrégats sont liés par `journals.publisher_id` (FK) mais manipulés par des opérations distinctes — séparer les ports réduit la surface sur laquelle chaque call site s'engage.

Le trouve-ou-crée et l'enrichissement, alimentés par le pipeline, vivent à part dans `application/ports/pipeline/journals.py`.

La méthode `find_shared_title_journal_pairs` vit ici : c'est une query sur la table `journals`, appelée par le service de fusion d'éditeurs pour détecter les conflits avant `merge_publisher_into`.
"""

from typing import Any, Protocol

from pydantic import BaseModel

from domain.journals.journal import Journal, JournalType, OaModel


class JournalUpdate(BaseModel):
    """Champs éditables d'une revue, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `title_normalized`, dérivé de `title`, est posé par le repository.

    `journal_type` et `oa_model` portent les types du domaine : leurs jeux de valeurs, que les enums SQL des mêmes noms reprennent, se vérifient ici plutôt que chez chaque appelant.
    """

    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: OaModel | None = None
    journal_type: JournalType | None = None
    is_academic: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None


class JournalRepository(Protocol):
    """Contrat d'édition et de fusion curées de l'agrégat Journal."""

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
    ) -> list[dict[str, Any]]:
        """Paires de revues (une du `target_publisher_id`, une du `source_publisher_id`) partageant le même `title_normalized`. Chaque ligne porte `target_journal_id`, `source_journal_id` et les six valeurs ISSN/eISSN/ISSN-L des deux côtés, pour que le service détecte les conflits d'ISSN en une seule requête."""
        ...

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id` : transfère publications, formes de nom et paiements APC, enrichit la cible par COALESCE, supprime la source, puis recalcule les compteurs de publications."""
        ...
