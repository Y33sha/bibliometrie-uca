"""Phase `metadata_correction` — sous-étape **cluster** (corrections relationnelles).

Group-by-DOI sur les `source_publications` `book`/`book_chapter` : un ouvrage et son
chapitre partageant un DOI signalent que le chapitre porte le DOI de l'ouvrage par erreur
→ le chapitre perd le DOI (il cesse alors de fusionner avec l'ouvrage au matching).

`doc_type` lus = **canoniques** (la sous-étape unaire a déjà tourné). Idempotent et
auto-cicatrisant : on repart du **DOI brut reconstruit** (`raw_metadata.doi`), donc un
chapitre dont l'ouvrage a disparu/changé de type récupère son DOI au run suivant.

Périmètre : ouvrage/chapitre seulement. chapitre/chapitre (comparaison de titre floue) et
thèse/article (mistype → correction de `doc_type`) sont différés — cf. fiche chantier.
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import (
    DoiClusterRow,
    DoiCorrectionUpdate,
    MetadataCorrectionQueries,
)
from domain.source_publications.correction import (
    DistinctMergeCase,
    KeyGroupMember,
    detect_erroneous_key_holders,
)
from domain.source_publications.raw_metadata import raw_value, stash_entry

_PERSIST_BATCH = 5000


def _compute_update(
    row: DoiClusterRow, case: DistinctMergeCase | None
) -> DoiCorrectionUpdate | None:
    """État cible d'une SP : si `case` (DOI erroné selon le domaine), DOI nullé avec le brut
    stashé sous la provenance `case` ; sinon DOI brut restauré. Retourne `None` si rien ne
    change (idempotence / auto-cicatrisation). La *décision* vient du domaine, pas d'ici."""
    raw_doi = raw_value(row.raw_metadata, "doi", row.doi)
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k != "doi"}

    if case is not None:
        new_doi = None
        raw_metadata["doi"] = stash_entry(raw_doi, case.value)
    else:
        new_doi = raw_doi

    if new_doi == row.doi and raw_metadata == row.raw_metadata:
        return None
    return DoiCorrectionUpdate(row.id, new_doi, raw_metadata)


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Regroupe par DOI brut, demande au domaine quels DOI sont erronés, renvoie les mises à jour.

    Pur (hors I/O) et sans décision métier : la règle (qui perd le DOI) vit dans
    `detect_erroneous_doi_holders` ; ici on ne fait que regrouper et persister l'état cible."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.raw_doi].append(row)

    updates: list[DoiCorrectionUpdate] = []
    for members in groups.values():
        case_by_id = dict(
            detect_erroneous_key_holders(
                [KeyGroupMember(m.id, m.doc_type, m.title_normalized) for m in members]
            )
        )
        for m in members:
            if m.doc_type != "book_chapter":
                continue
            upd = _compute_update(m, case_by_id.get(m.id))
            if upd is not None:
                updates.append(upd)
    return updates


def run(conn: Connection, queries: MetadataCorrectionQueries, logger: logging.Logger) -> None:
    """Passe cluster ouvrage/chapitre : nulle le DOI des chapitres portant le DOI de l'ouvrage."""
    rows = queries.fetch_doi_cluster_candidates(conn)
    logger.info("metadata_correction (cluster) : %d SP book/book_chapter examinées", len(rows))

    updates = compute_updates(rows)
    logger.info("  %d corrections de DOI à appliquer", len(updates))

    total = 0
    for start in range(0, len(updates), _PERSIST_BATCH):
        total += queries.persist_doi_corrections(conn, updates[start : start + _PERSIST_BATCH])
        conn.commit()
    logger.info("✓ %d DOI corrigés (ouvrage/chapitre)", total)
