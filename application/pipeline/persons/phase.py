"""Orchestrateur unique de la phase personnes.

Enchaîne, sur une seule transaction, les étapes qui rattachent les `source_authorships` aux
personnes de façon ordre-indépendante :

1. **enforce** — réapplique les épinglages admin (`confirmed_authorships`, must-link) : entrée
   fixe reposée avant toute dérivation.
2. **reset** — réinitialise les attributions dérivées (arbitrage des conflits d'identifiant par
   consensus, recompute complet du cross-source).
3. **match** — rattache aux personnes existantes ou déjà résolues, sans jamais créer.
4. **create** — re-juge les signatures restées non liées (cross-source rejoué) puis crée les
   vraies inconnues.
5. **populate** — régénère les formes de nom canoniques (initiales comprises).
6. **purge** — re-orpheline les formes devenues ambiguës après régénération et supprime les
   personnes vidées.

Le commit est laissé au caller : `run_pipeline` (une connexion, un commit) et la CLI (commit,
ou rollback en dry-run) sont deux coquilles qui appellent cet orchestrateur.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.persons.cascade import build_metrics, create, match
from application.pipeline.persons.populate_person_name_forms import populate
from application.pipeline.persons.purge import purge
from application.pipeline.persons.reset import reset
from application.ports.pipeline.name_forms import NameFormsQueries
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository


def run(
    conn: Connection,
    persons_queries: PersonsCreateQueries,
    name_forms_queries: NameFormsQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    dry_run: bool = False,
) -> PhaseMetrics:
    """Exécute la phase personnes de bout en bout et rend ses métriques.

    Le commit (ou le rollback en dry-run) est laissé au caller.
    """
    n_enforced = authorship_repo.enforce_confirmed_authorships()
    if n_enforced:
        logger.info("Épinglages réappliqués : %d signatures recalées", n_enforced)

    reset_counts = reset(conn, persons_queries, logger, person_repo=person_repo)
    match_result = match(conn, persons_queries, logger, person_repo=person_repo, dry_run=dry_run)
    create_result = create(conn, persons_queries, logger, person_repo=person_repo, dry_run=dry_run)
    populate(conn, name_forms_queries, logger)
    purge_counts = purge(conn, persons_queries, logger)

    return build_metrics(
        match_result,
        create_result,
        transferred=reset_counts["transferred"],
        reset_cross=reset_counts["reset_cross"],
        reorphaned=purge_counts["reorphaned"],
        deleted_persons=purge_counts["deleted_persons"],
    )
