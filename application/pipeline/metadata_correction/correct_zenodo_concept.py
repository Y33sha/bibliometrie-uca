"""Phase `metadata_correction` — sous-étape **Zenodo concept** (substitution unaire de DOI).

Le DOI effectif d'une SP Zenodo est son *concept* DOI (agnostique aux versions), pas le DOI de version porté par la source. La phase `zenodo_doi` (en amont) a résolu et mis en cache le concept dans `external_ids.zenodo_concept_doi`. Cette sous-étape applique la substitution **en place** : `doi = concept` dans la colonne, version source stashée dans `raw_metadata.doi` (`corrected_by = ZENODO_CONCEPT_DOI`). Concept + versions convergent ainsi vers une publication unique sans qu'aucun site de lecture aval ne recalcule l'effective.

Correction **unaire** (décidable depuis la seule SP + son cache) ; elle ne touche que `raw_metadata.doi`, comme la sous-étape cluster — mais sur un sous-ensemble disjoint de SP (datasets Zenodo vs `book`/`book_chapter`), donc aucune SP ne reçoit les deux corrections de DOI. Idempotent et auto-cicatrisant : on repart du **DOI brut reconstruit** (`raw_metadata.doi`), donc un dépôt qui cesse d'être versionné (concept == version) récupère son DOI source au run suivant. Tourne **avant** la sous-étape cluster, qui regroupe alors sur le concept.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import (
    DoiCorrectionUpdate,
    MetadataCorrectionQueries,
    ZenodoConceptRow,
)
from domain.publications.identifiers import clean_doi
from domain.source_publications.raw_metadata import raw_value, stash_entry

# Provenance inscrite dans `raw_metadata.doi.corrected_by` quand le concept DOI a remplacé
# la version source.
ZENODO_CONCEPT_DOI = "ZENODO_CONCEPT_DOI"

_PERSIST_BATCH = 5000


def _compute_update(row: ZenodoConceptRow) -> DoiCorrectionUpdate | None:
    """État cible d'une SP Zenodo : concept DOI normalisé en colonne, version source stashée
    sous `ZENODO_CONCEPT_DOI`. Si le concept est invalide ou égal à la version (dépôt non
    versionné), le DOI brut est restauré. `None` si rien ne change (idempotence)."""
    concept = clean_doi(row.concept_doi)
    raw_doi = raw_value(row.raw_metadata, "doi", row.doi)
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k != "doi"}

    if concept and concept != raw_doi:
        new_doi: str | None = concept
        raw_metadata["doi"] = stash_entry(raw_doi, ZENODO_CONCEPT_DOI)
    else:
        new_doi = raw_doi

    if new_doi == row.doi and raw_metadata == row.raw_metadata:
        return None
    return DoiCorrectionUpdate(row.id, new_doi, raw_metadata)


def compute_updates(rows: list[ZenodoConceptRow]) -> list[DoiCorrectionUpdate]:
    """Calcule les substitutions concept→colonne pour les SP candidates. Pur (hors I/O)."""
    return [upd for row in rows if (upd := _compute_update(row)) is not None]


def run(conn: Connection, queries: MetadataCorrectionQueries, logger: logging.Logger) -> None:
    """Substitue le concept DOI Zenodo dans la colonne `doi` des SP à concept caché."""
    rows = queries.fetch_zenodo_concept_candidates(conn)
    logger.info("metadata_correction (zenodo) : %d SP à concept DOI caché", len(rows))

    updates = compute_updates(rows)
    logger.info("  %d substitutions concept→colonne à appliquer", len(updates))

    total = 0
    for start in range(0, len(updates), _PERSIST_BATCH):
        total += queries.persist_doi_corrections(conn, updates[start : start + _PERSIST_BATCH])
        conn.commit()
    logger.info("✓ %d DOI substitués par le concept Zenodo", total)
