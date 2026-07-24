"""Port PublicationRepository — contrat d'accès à l'agrégat Publication."""

from dataclasses import dataclass
from typing import Protocol

from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication


@dataclass(frozen=True, slots=True)
class PubByDoi:
    """Projection de lecture retournée par `find_by_doi` : l'id de la publication portant ce DOI, sans hydrater l'agrégat complet."""

    id: int


class PublicationRepository(Protocol):
    """Contrat d'accès à l'agrégat Publication (tables publications, source_publications et distinct_publications)."""

    # ── Chargement / persistance de l'aggregate ────────────────────

    def find_by_id(self, pub_id: int) -> Publication | None:
        """Hydrate l'agrégat `Publication` depuis `publications` (attributs canoniques), ou `None` si absente. Les authorships ne sont pas chargées ici (projection lecture séparée au besoin)."""
        ...

    def save(self, pub: Publication) -> None:
        """Persiste l'état mutable de l'agrégat `Publication` (tous les champs éditables ; `pub_year` reste immuable après création). Requiert `pub.id` posé."""
        ...

    # ── Recherches (projections de lecture) ────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None:
        """Cherche une publication par DOI (insensible à la casse). `None` si aucune."""
        ...

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        """Ids des publications rattachées à ce journal. Utilisé pour requalifier le stock quand un input éditable du journal (ex. `journal_type`) change."""
        ...

    def find_doc_types_by_ids(self, pub_ids: list[int]) -> dict[int, str]:
        """`doc_type` de chaque publication demandée, en une lecture. Une publication absente de la table manque de la réponse — un refresh peut l'avoir supprimée."""
        ...

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        """Met à jour le statut OA d'une publication (vérification Unpaywall) et pose `unpaywall_checked_at`."""
        ...

    def mark_unpaywall_checked(self, pub_id: int) -> None:
        """Pose `unpaywall_checked_at = now()` à statut inchangé (vérification Unpaywall neutre : statut identique, DOI non trouvé, ou diamond préservé)."""
        ...

    def update_sources(self, pub_id: int) -> None:
        """Recalcule `publications.sources` par agrégation des `source_publications` rattachées."""
        ...

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_publications(self, pub_id: int) -> list[SourcePublication]:
        """Les `SourcePublication` attachées à une publication canonique, matière de l'agrégation canonique (`refresh_from_sources`)."""
        ...

    def get_converged_secondary_ids(self, pub_id: int) -> frozenset[int]:
        """Ids des `source_publications` de `pub_id` dont le DOI a été substitué par une correction de convergence (forme secondaire : version, variante, pièce d'un dataset). L'agrégation les dépriorise pour que les scalaires descriptifs viennent de l'enregistrement canonique."""
        ...

    def get_journal_type(self, journal_id: int) -> str | None:
        """`journal_type` d'un journal, pour la re-correction canonique journal-dépendante dans `refresh_from_sources`. None si le journal n'existe pas ou son type n'est pas posé."""
        ...

    # ── Création ───────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
    ) -> int:
        """Insère une publication (INSERT brut, la déduplication relève du caller) et retourne son `id`. Les colonnes hors NOT NULL et DOI prennent leur défaut ; `save` les pose."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la publication `source_id` dans `target_id` : transfère `source_publications` et authorships (dédup par personne), repointe les paires `distinct_publications`, puis supprime la source. Les métadonnées canoniques de la cible sont recomputées ensuite par le caller via `refresh_from_sources`."""
        ...

    # ── Suppression ────────────────────────────────────────────────

    def delete(self, pub_id: int) -> None:
        """Supprime une publication. Le cascade DB nettoie `authorships`, `distinct_publications`, `publication_subjects` ; `apc_payments` et `source_publications.publication_id` passent à NULL."""
        ...

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(
        self,
        pub_id_a: int,
        pub_id_b: int,
    ) -> tuple[int, int] | None:
        """Marque deux publications comme distinctes (idempotent). Retourne `(a, b)` si la paire vient d'être insérée, `None` sinon."""
        ...
