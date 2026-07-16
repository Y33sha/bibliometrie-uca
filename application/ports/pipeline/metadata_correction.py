"""Port : SQL de la phase `metadata_correction`.

Implémenté par `infrastructure.queries.pipeline.metadata_correction.PgMetadataCorrectionQueries`.

La phase persiste sur `source_publications` les valeurs corrigées par les règles de `domain.source_publications.correction`, pour que le matching aval lise des colonnes déjà corrigées. Trois sous-étapes s'appuient sur ce port : la correction unaire, qui traite chaque `source_publication` isolément ; le rattachement d'un journal par préfixe de DOI ; et la correction de DOI par groupe de `source_publications` partageant un même DOI.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection

from domain.source_publications.correction import DoiClusterCase, MetadataForCorrection
from domain.types import JsonValue


class UnaryCorrectionRow(NamedTuple):
    """Une `source_publication` candidate à la correction unaire, jointe à son journal.

    Porte les champs du contrat des règles (`for_correction`) et ceux dont la phase seule se sert : `id` pour persister, `source` pour `map_doc_type`, `external_ids` et `raw_metadata` pour le stash et la reconstruction du brut.

    L'adapter construit les lignes par appariement de noms : chaque champ porte le nom de la colonne qui l'alimente.
    """

    id: int
    source: str
    title: str
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    oa_status: str | None
    urls: list[str] | None
    external_ids: dict[str, JsonValue]
    journal_type: str | None
    oa_model: str | None
    raw_metadata: dict[str, JsonValue]
    embargo_expired: bool
    self_declared_preprint: bool

    def for_correction(self) -> MetadataForCorrection:
        """Projette la ligne vers le contrat d'entrée des règles."""
        return MetadataForCorrection(
            title=self.title,
            doc_type=self.doc_type,
            doi=self.doi,
            journal_id=self.journal_id,
            oa_status=self.oa_status,
            urls=self.urls,
            journal_type=self.journal_type,
            oa_model=self.oa_model,
            embargo_expired=self.embargo_expired,
            self_declared_preprint=self.self_declared_preprint,
        )


class CorrectionUpdate(NamedTuple):
    """Une mise à jour à persister : colonnes effectives + `external_ids` + sidecar `raw_metadata`."""

    id: int
    doc_type: str | None
    oa_status: str | None
    external_ids: dict[str, JsonValue]
    raw_metadata: dict[str, JsonValue]


class JournalDoiPrefixRow(NamedTuple):
    """Un préfixe DOI et la revue qui le porte. Matière du longest-prefix-match qui rattache une `source_publication` à sa revue."""

    doi_prefix: str
    journal_id: int


class JournalByDoiRow(NamedTuple):
    """Une `source_publication` candidate au rattachement du journal par préfixe DOI : son id, son DOI courant, son `journal_id` courant et `raw_metadata` (reconstruction du brut `journal_id` et garde « ne corriger que le manquant »)."""

    id: int
    doi: str | None
    journal_id: int | None
    raw_metadata: dict[str, JsonValue]


class JournalCorrectionUpdate(NamedTuple):
    """Une mise à jour de rattachement : colonne `journal_id` (posée ou restaurée à NULL) + sidecar `raw_metadata`. Produite par la sous-étape `journal_by_doi`, persistée via `persist_journal_corrections`."""

    id: int
    journal_id: int | None
    raw_metadata: dict[str, JsonValue]


class DoiClusterRow(NamedTuple):
    """Une `source_publication` candidate à la correction de DOI par cluster.

    `raw_doi` est le DOI **source reconstruit** (`raw_metadata.doi.raw` ou colonne `doi`), en minuscules — clé de regroupement par DOI. `title_normalized` sert à la comparaison chapitre/chapitre. `canonical_doi` est le DOI de l'œuvre canonique quand `raw_doi` est une **forme secondaire** DataCite (version, forme variante, ou fichier de package), sinon `None` ; `same_work_case` porte alors le cas correspondant."""

    id: int
    doc_type: str | None
    doi: str | None
    title_normalized: str | None
    raw_metadata: dict[str, JsonValue]
    raw_doi: str
    canonical_doi: str | None
    same_work_case: DoiClusterCase | None


class DoiCorrectionUpdate(NamedTuple):
    """Une mise à jour de correction de DOI : colonne `doi` (nullée, restaurée ou substituée) + sidecar. Produite par la correction de DOI par cluster (convergence même-œuvre ou nullage de DOI partagé à tort), persistée via `persist_doi_corrections`."""

    id: int
    doi: str | None
    raw_metadata: dict[str, JsonValue]


class MetadataCorrectionQueries(Protocol):
    """Lecture des candidats de chaque sous-étape, et écriture en lot des corrections qu'elles produisent."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[UnaryCorrectionRow]:
        """Toutes les `source_publications`, avec join `journals` et `raw_metadata`.

        Pas de pré-filtre par règle : certaines règles sont inconditionnelles sur `doc_type` (URL theses.fr/DUMAS), et une `source_publication` sans `doc_type` reste candidate. Le filtrage fin est porté par la cascade `effective_metadata`.
        """
        ...

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[UnaryCorrectionRow]:
        """Les `source_publications` rattachées à un journal (`journal_id = :jid`).

        Recompute ciblé après un changement de `journal_type` (hook admin) : seules ces `source_publications` voient leur correction journal-dépendante bouger."""
        ...

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`, marque `keys_dirty` — `doc_type` et `external_ids` sont des clés de matching, dont la mutation appelle une réconciliation. Retourne le nombre de lignes mises à jour."""
        ...

    def fetch_journal_doi_prefixes(self, conn: Connection) -> list[JournalDoiPrefixRow]:
        """Toutes les revues portant un `doi_prefix`. Carte chargée en mémoire pour le longest-prefix-match (volume négligeable)."""
        ...

    def fetch_journal_by_doi_candidates(self, conn: Connection) -> list[JournalByDoiRow]:
        """`source_publications` candidates au rattachement : orphelines à DOI (`journal_id IS NULL AND doi IS NOT NULL`) et déjà rattachées par préfixe (`raw_metadata ? 'journal_id'`, pour la ré-évaluation auto-cicatrisante)."""
        ...

    def persist_journal_corrections(
        self, conn: Connection, updates: list[JournalCorrectionUpdate]
    ) -> int:
        """UPDATE en lot de la colonne `journal_id` + `raw_metadata`, bump `updated_at`, marque `keys_dirty` (pour que la réconciliation rafraîchisse le `journal_id` canonique — bien que `journal_id` ne soit pas une clé de matching). Retourne le nombre de lignes."""
        ...

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        """Les membres des groupes-DOI candidats à la correction par cluster, avec leur `canonical_doi` éventuel : groupes contenant un `book`/`book_chapter`, groupes dont le DOI est un DOI de version DataCite (`IsVersionOf`), et `source_publications` déjà corrigées (`raw_metadata.doi`) pour la ré-évaluation auto-cicatrisante."""
        ...

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        """UPDATE en lot de la colonne `doi` + `raw_metadata`, bump `updated_at`, marque `keys_dirty` — le DOI est une clé de confirmation, dont la mutation appelle une réconciliation. Retourne le nombre de lignes mises à jour."""
        ...
