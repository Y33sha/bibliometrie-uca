"""Orchestrateur unique de la phase personnes.

Les six étapes tournent sur **une seule** transaction (ouverte via `open_tx`) : `reset` peut détacher des signatures (conflits d'identifiant), la cascade les re-résout, et le détachement cross-source final retire les liens sans appui. Ces mutations dérivées doivent committer ensemble — un crash en cours de phase laisserait sinon des signatures détachées jusqu'au run suivant.

1. **enforce** — réapplique les épinglages admin (`confirmed_authorships`, must-link) : entrée fixe reposée avant toute dérivation.
2. **arbitrage des conflits d'identifiant** — tranche par consensus des porteurs (les signatures captées repassent à NULL).
3. **cascade** — un seul balayage en deux passes internes, sur des index vivants partagés : `match` (rattachement ferme + cross-source), puis `create` (rattrapage cross-source + création des inconnues).
4. **détachement cross-source** — les liens cross-source restés sans appui ferme repassent à NULL.
5. **populate** — régénère les formes de nom canoniques.
6. **purge** — re-orpheline les formes devenues ambiguës après régénération et supprime les personnes vidées.

Le rattachement est ordre-indépendant : le résultat ne dépend pas de la séquence d'ingestion des sources — propriété de l'algorithme (recompute complet, arbitrage par consensus, lectures d'agrégat sur le snapshot), non de la transaction.

Le commit est porté par `open_tx` : `managed_transaction` commite en sortie de bloc si succès, rollback sinon. `phase_persons` de `run_pipeline` s'y réduit au câblage.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.persons.arbitrate_identifiers import arbitrate_identifier_conflicts
from application.pipeline.persons.cascade import run_cascade
from application.pipeline.persons.metrics import build_metrics, log_matching_breakdown
from application.pipeline.persons.populate_person_name_forms import populate
from application.pipeline.persons.purge import purge
from application.ports.pipeline.person_name_forms import PersonNameFormsQueries
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.pipeline.transaction import OpenTransaction
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository


def run(
    open_tx: OpenTransaction,
    persons_queries: PersonsCreateQueries,
    name_forms_queries: PersonNameFormsQueries,
    logger: logging.Logger,
    *,
    person_repo_factory: Callable[[Connection], PersonRepository],
    authorship_repo_factory: Callable[[Connection], AuthorshipRepository],
) -> PhaseMetrics:
    """Exécute la phase personnes de bout en bout, sur une transaction gérée, et rend ses métriques."""
    logger.info("▶ persons")
    t0 = time.perf_counter()
    with open_tx() as conn:
        person_repo = person_repo_factory(conn)
        authorship_repo = authorship_repo_factory(conn)

        n_enforced = authorship_repo.enforce_confirmed_authorships()
        if n_enforced:
            logger.info("Épinglages réappliqués : %d signatures recalées", n_enforced)

        arbitration = arbitrate_identifier_conflicts(
            conn, persons_queries, logger, person_repo=person_repo
        )
        cascade_result = run_cascade(conn, persons_queries, logger, person_repo=person_repo)

        # Les signatures cross-source qu'aucune passe n'a re-résolues ont perdu leur ancre ferme → détachées.
        stale = sorted(
            cascade_result.cross_source_candidate_ids - cascade_result.resolved_cross_source_ids
        )
        cross_source_detached = persons_queries.detach_authorships(conn, stale)
        if cross_source_detached:
            logger.info(
                "  %d signature(s) cross-source sans appui détachée(s)", cross_source_detached
            )

        populate(conn, name_forms_queries, logger)
        purge_counts = purge(conn, persons_queries, logger)

        metrics = build_metrics(
            cascade_result,
            transferred=arbitration["transferred"],
            cross_source_detached=cross_source_detached,
            reorphaned=purge_counts["reorphaned"],
            deleted_persons=purge_counts["deleted_persons"],
        )
        log_matching_breakdown(logger, cascade_result)
    logger.info("✓ persons terminé en %.1fs", time.perf_counter() - t0)
    return metrics
