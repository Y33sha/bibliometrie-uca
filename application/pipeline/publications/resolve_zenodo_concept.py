"""Résout le concept DOI des source_publications Zenodo (hors chemin chaud).

Phase `zenodo_doi`, exécutée AVANT `metadata_correction` : pour chaque
source_publication au DOI Zenodo sans `external_ids.zenodo_concept_doi`, appelle
l'API Zenodo (`conceptdoi`) et **met en cache** le concept DOI dans `external_ids`.
C'est un enrichissement (fetch + cache) : la substitution effective du DOI
(concept en colonne, version dans `raw_metadata`) est portée a posteriori par la
sous-étape Zenodo de `metadata_correction`, qui consomme ce cache. Le cache
survit au re-normalize (merge `||` des `external_ids`), donc pas de re-fetch.

Le concept DOI est l'identifiant stable, agnostique aux versions. Un dépôt non
versionné n'expose pas de `conceptdoi` : on stocke alors le DOI de la SP comme
son propre concept (il se canonicalise sur lui-même). La SP est ainsi toujours
résolue — et donc exclue des runs suivants : la phase est idempotente, sans
double appel API. Une erreur temporaire (rate-limit, timeout) laisse la SP non
résolue, retentée au prochain run.

L'orchestrateur dépend des ports `ZenodoConceptQueries` et `ZenodoResolver`. Le
point d'entrée CLI est dans `interfaces/cli/pipeline/resolve_zenodo_concept.py`.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.zenodo_concept import ZenodoConceptQueries
from application.ports.pipeline.zenodo_resolver import ZenodoResolver
from domain.sources.zenodo import ZenodoResolutionError


def run(
    conn: Connection,
    queries: ZenodoConceptQueries,
    resolver: ZenodoResolver,
    logger: logging.Logger,
) -> None:
    docs = queries.fetch_zenodo_source_publications_without_concept(conn)
    logger.info("%d source_publications Zenodo sans concept DOI", len(docs))

    resolved = 0
    failed = 0
    for i, doc in enumerate(docs):
        try:
            concept_doi = resolver.resolve_concept_doi(doc.doi)
        except ZenodoResolutionError as e:
            logger.warning("  SP %d (%s) : %s — retenté au prochain run", doc.id, doc.doi, e)
            failed += 1
            continue

        # Pas de concept exposé (dépôt non versionné) → la SP est son propre
        # concept ; on pose son DOI pour la rendre résolue et idempotente.
        queries.set_concept_doi(conn, doc.id, concept_doi or doc.doi)
        resolved += 1

        if (i + 1) % 100 == 0:
            conn.commit()
            logger.info("  %d/%d traités...", i + 1, len(docs))

    conn.commit()
    logger.info("Terminé : %d concept DOI résolus, %d échecs temporaires", resolved, failed)
