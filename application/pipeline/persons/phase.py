"""Orchestrateur unique de la phase personnes.

Phase mono-transaction : les six étapes tournent sur **une seule** transaction gérée (ouverte via `open_tx`), et rattachent les `source_authorships` aux personnes de façon ordre-indépendante :

1. **enforce** — réapplique les épinglages admin (`confirmed_authorships`, must-link) : entrée fixe reposée avant toute dérivation.
2. **reset** — réinitialise les attributions dérivées (arbitrage des conflits d'identifiant par consensus, recompute complet du cross-source).
3. **match** — rattache aux personnes existantes ou déjà résolues, sans jamais créer.
4. **create** — re-juge les signatures restées non liées (cross-source rejoué) puis crée les vraies inconnues.
5. **populate** — régénère les formes de nom canoniques.
6. **purge** — re-orpheline les formes devenues ambiguës après régénération et supprime les personnes vidées.

Le commit est porté par `open_tx` : `managed_transaction` commite en sortie de bloc si succès, rollback sinon. `phase_persons` de `run_pipeline` s'y réduit au câblage.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.persons.cascade import create, match
from application.pipeline.persons.metrics import build_metrics, log_matching_breakdown
from application.pipeline.persons.populate_person_name_forms import populate
from application.pipeline.persons.purge import purge
from application.pipeline.persons.reset import reset
from application.ports.pipeline.name_forms import NameFormsQueries
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.pipeline.transaction import OpenTransaction
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository


def run(
    open_tx: OpenTransaction,
    persons_queries: PersonsCreateQueries,
    name_forms_queries: NameFormsQueries,
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

        reset_counts = reset(conn, persons_queries, logger, person_repo=person_repo)
        match_result = match(conn, persons_queries, logger, person_repo=person_repo)
        create_result = create(conn, persons_queries, logger, person_repo=person_repo)
        populate(conn, name_forms_queries, logger)
        purge_counts = purge(conn, persons_queries, logger)

        metrics = build_metrics(
            match_result,
            create_result,
            transferred=reset_counts["transferred"],
            reset_cross=reset_counts["reset_cross"],
            reorphaned=purge_counts["reorphaned"],
            deleted_persons=purge_counts["deleted_persons"],
        )
        log_matching_breakdown(logger, match_result, create_result)
    logger.info("✓ persons terminé en %.1fs", time.perf_counter() - t0)
    return metrics
