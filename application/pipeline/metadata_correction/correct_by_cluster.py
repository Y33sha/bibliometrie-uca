"""Phase `metadata_correction` — sous-étape **cluster** (corrections de DOI par groupe).

Group-by-DOI sur les `source_publications` : le domaine déduit, pour chaque groupe partageant
un DOI, le DOI effectif de chaque membre. Deux familles de cas (extensibles) :

- **convergence (même œuvre)** : une forme secondaire DataCite converge sur le DOI de l'œuvre
  canonique — version → concept (`IsVersionOf`), forme variante / copie repository → version
  publiée (`IsVariantFormOf`), fichier d'un dépôt → dépôt parent (`IsPartOf`) ;
- **divergence** : un DOI partagé par des œuvres distinctes (ouvrage/chapitre, chapitres de
  titres différents) est nullé sur le ou les mauvais côtés, sinon le matching les fusionnerait.

`doc_type` lus = **canoniques** (la sous-étape unaire a déjà tourné). Idempotent et
auto-cicatrisant : on repart du **DOI brut reconstruit** (`raw_metadata.doi`), donc une SP
dont la relation/le conflit a disparu récupère son DOI source au run suivant.
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
    DoiClusterDecision,
    DoiClusterMember,
    resolve_cluster_doi_corrections,
)
from domain.source_publications.raw_metadata import raw_value, stash_entry

_PERSIST_BATCH = 5000


def _compute_update(
    row: DoiClusterRow, decision: DoiClusterDecision | None
) -> DoiCorrectionUpdate | None:
    """État cible d'une SP : selon la décision du domaine, DOI nullé (`target_doi=None`) ou
    substitué (concept), le brut stashé sous la provenance du cas ; sans décision, ou si la
    cible égale le brut (dépôt non versionné), le DOI brut est restauré. Retourne `None` si
    rien ne change (idempotence / auto-cicatrisation). La *décision* vient du domaine."""
    raw_doi = raw_value(row.raw_metadata, "doi", row.doi)
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k != "doi"}

    if decision is None or decision.target_doi == raw_doi:
        new_doi = raw_doi
    else:
        new_doi = decision.target_doi
        raw_metadata["doi"] = stash_entry(raw_doi, decision.case.value)

    if new_doi == row.doi and raw_metadata == row.raw_metadata:
        return None
    return DoiCorrectionUpdate(row.id, new_doi, raw_metadata)


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Regroupe par DOI brut, demande au domaine le DOI cible de chaque membre, renvoie les
    mises à jour.

    Pur (hors I/O) et sans décision métier : la règle vit dans
    `resolve_cluster_doi_corrections` ; ici on ne fait que regrouper et persister l'état cible."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.raw_doi].append(row)

    updates: list[DoiCorrectionUpdate] = []
    for members in groups.values():
        decision_by_id = {
            d.id: d
            for d in resolve_cluster_doi_corrections(
                [
                    DoiClusterMember(
                        m.id, m.doc_type, m.title_normalized, m.canonical_doi, m.same_work_case
                    )
                    for m in members
                ]
            )
        }
        for m in members:
            upd = _compute_update(m, decision_by_id.get(m.id))
            if upd is not None:
                updates.append(upd)
    return updates


def run(conn: Connection, queries: MetadataCorrectionQueries, logger: logging.Logger) -> None:
    """Passe cluster : fait converger les formes secondaires DataCite sur l'œuvre canonique
    (version → concept, variante → version publiée, fichier → dépôt parent) et nulle le DOI
    des chapitres portant le DOI de l'ouvrage."""
    rows = queries.fetch_doi_cluster_candidates(conn)
    logger.info("metadata_correction (cluster) : %d SP examinées", len(rows))

    updates = compute_updates(rows)
    logger.info("  %d corrections de DOI à appliquer", len(updates))

    total = 0
    for start in range(0, len(updates), _PERSIST_BATCH):
        total += queries.persist_doi_corrections(conn, updates[start : start + _PERSIST_BATCH])
        conn.commit()
    logger.info("✓ %d DOI corrigés (cluster)", total)
