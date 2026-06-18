"""Port : SQL de la phase `metadata_correction`.

Implémenté par `infrastructure.queries.pipeline.metadata_correction.PgMetadataCorrectionQueries`.

La phase persiste sur `source_publications` les valeurs corrigées par les règles
de `domain.source_publications.correction`, pour que le matching aval lise des colonnes
déjà corrigées. Sous-étape unaire (per-record) ici ; la sous-étape relationnelle
(group-by-DOI) viendra en Phase 2.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection

from domain.source_publications.correction import SourcePublicationForCorrection
from domain.types import JsonValue


class CorrectionUpdate(NamedTuple):
    """Une mise à jour à persister : colonnes effectives + `external_ids` + sidecar `raw_metadata`."""

    id: int
    doc_type: str | None
    journal_id: int | None
    oa_status: str | None
    external_ids: dict[str, JsonValue]
    raw_metadata: dict[str, JsonValue]


class DoiClusterRow(NamedTuple):
    """Une SP `book`/`book_chapter` candidate à la correction relationnelle de DOI.

    `raw_doi` est le DOI **source reconstruit** (`raw_metadata.doi.raw` ou colonne `doi`),
    en minuscules — clé de regroupement par DOI. `title_normalized` sert à la comparaison
    chapitre/chapitre."""

    id: int
    doc_type: str | None
    doi: str | None
    title_normalized: str | None
    raw_metadata: dict[str, JsonValue]
    raw_doi: str


class DoiCorrectionUpdate(NamedTuple):
    """Une mise à jour de correction de DOI : colonne `doi` (nullée, restaurée ou
    substituée) + sidecar. Partagée par la correction relationnelle (cluster) et la
    substitution Zenodo (concept), qui produisent toutes deux un état cible de la
    colonne `doi` à persister via `persist_doi_corrections`."""

    id: int
    doi: str | None
    raw_metadata: dict[str, JsonValue]


class ZenodoConceptRow(NamedTuple):
    """Une SP au DOI Zenodo avec son concept DOI mis en cache (`external_ids.zenodo_concept_doi`).

    `doi` est la valeur **courante** de la colonne (potentiellement déjà substituée) ;
    `concept_doi` est le concept caché par la phase `zenodo_doi` ; `raw_metadata`
    reconstruit le DOI source d'origine (la version). La correction substitue le concept
    dans la colonne et stashe la version dans `raw_metadata.doi`."""

    id: int
    doi: str | None
    concept_doi: str
    raw_metadata: dict[str, JsonValue]


class MetadataCorrectionQueries(Protocol):
    """Opérations SQL de la phase `metadata_correction`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[SourcePublicationForCorrection]:
        """Toutes les `source_publications`, avec join `journals` et `raw_metadata`.

        Pas de pré-filtre par règle : certaines règles sont inconditionnelles sur
        `doc_type` (URL theses.fr/DUMAS), donc une SP sans `doc_type` reste
        candidate. Le filtrage fin est porté par la cascade `effective_metadata`.
        """
        ...

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[SourcePublicationForCorrection]:
        """Les `source_publications` rattachées à un journal (`journal_id = :jid`).

        Recompute ciblé après un changement de `journal_type` (hook admin) : seules
        ces SP voient leur correction journal-dépendante bouger."""
        ...

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`
        (pour que le refresh stale aval ré-agrège la publication). Retourne le
        nombre de lignes mises à jour."""
        ...

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        """Les SP `book`/`book_chapter` ayant un DOI (brut reconstruit), pour la correction
        relationnelle group-by-DOI. Inclut les SP déjà corrigées (`raw_metadata.doi`) pour
        la ré-évaluation auto-cicatrisante."""
        ...

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        """UPDATE en lot de la colonne `doi` + `raw_metadata`, bump `updated_at`. Retourne le
        nombre de lignes mises à jour."""
        ...

    def fetch_zenodo_concept_candidates(self, conn: Connection) -> list[ZenodoConceptRow]:
        """Les SP au concept DOI Zenodo caché (`external_ids ? 'zenodo_concept_doi'`), pour la
        substitution version→concept. Inclut les SP déjà substituées (`raw_metadata.doi`) pour
        la ré-évaluation auto-cicatrisante."""
        ...
