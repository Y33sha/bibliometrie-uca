"""Orchestrateur unique de la phase personnes.

Les six étapes tournent sur **une seule** transaction (ouverte via `open_tx`) : `reset` peut détacher des signatures (conflits d'identifiant), la cascade les re-résout, et le détachement cross-source final retire les liens sans appui. Ces mutations dérivées doivent committer ensemble — un crash en cours de phase laisserait sinon des signatures détachées jusqu'au run suivant.

1. **enforce** — réapplique les épinglages admin (`confirmed_authorships`, must-link) : entrée fixe reposée avant toute dérivation.
2. **identifiants mal placés et conflits d'identifiant** — sur un même consensus des porteurs, neutralise les identifiants mal placés, puis tranche les conflits d'attribution ; les signatures rattachées par un identifiant neutralisé ou capté repassent à NULL.
3. **cascade** — un seul balayage en deux passes internes, sur des index vivants partagés : `match` (rattachement ferme + cross-source), puis `create` (rattrapage cross-source + création des inconnues).
4. **détachement cross-source** — les liens cross-source restés sans appui ferme repassent à NULL.
5. **populate** — régénère les formes de nom canoniques.
6. **purge** — re-orpheline les formes devenues ambiguës après régénération, supprime les attributions d'identifiant automatiques qu'aucune signature ne porte, et supprime les personnes vidées.

Le rattachement est ordre-indépendant : le résultat ne dépend pas de la séquence d'ingestion des sources — propriété de l'algorithme (recompute complet, arbitrage par consensus, lectures d'agrégat sur le snapshot), non de la transaction.

`open_tx` gère le commit : `managed_transaction` commite en sortie de bloc si succès, rollback sinon.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_file_logger
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.persons.arbitrate_identifiers import arbitrate_identifier_conflicts
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.matching import PersonsMatchingQueries
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.name_forms import PersonNameFormsQueries
from pipeline.transformation.persons.person_writes import PersonWrites
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge


@dataclass(frozen=True)
class PersonsPhase:
    persons_queries: PersonsMatchingQueries
    name_forms_queries: PersonNameFormsQueries
    writes_factory: Callable[[Connection], PersonWrites]
    orphans_log: logging.Logger | None = None

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute la phase personnes de bout en bout, sur une transaction gérée, et rend ses métriques.

        `orphans_log` reçoit le motif de chaque signature du périmètre restée sans personne (`run_cascade`).
        """
        persons_queries, logger = self.persons_queries, ctx.logger
        with ctx.open_tx() as conn:
            writes = self.writes_factory(conn)

            n_enforced = persons_queries.enforce_confirmed_authorships(conn)
            if n_enforced:
                logger.info("Épinglages réappliqués : %d signatures recalées", n_enforced)

            arbitration = arbitrate_identifier_conflicts(
                conn, persons_queries, logger, writes=writes
            )
            cascade_result = run_cascade(
                conn,
                persons_queries,
                logger,
                writes=writes,
                orphans_log=self.orphans_log,
            )

            # Les signatures cross-source qu'aucune passe n'a re-résolues ont perdu leur ancre ferme → détachées.
            stale = sorted(
                cascade_result.cross_source_candidate_ids - cascade_result.resolved_cross_source_ids
            )
            cross_source_detached = persons_queries.detach_source_authorships(conn, stale)

            etape(logger, "Rafraîchissement des formes de nom associées aux personnes")
            t0 = time.perf_counter()
            with attente(f"{DERNIERE_BRANCHE}rafraîchissement en cours", logger) as ligne:
                populate(conn, self.name_forms_queries, logger)
                purge_counts = purge(conn, persons_queries, logger)
                ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")

            metrics = build_metrics(
                cascade_result,
                transferred=arbitration["transferred"],
                cross_source_detached=cross_source_detached,
                reorphaned=purge_counts["reorphaned"],
                deleted_persons=purge_counts["deleted_persons"],
            )
            metrics.resume = ""
        return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattachement des signatures aux personnes, et création des personnes inconnues.

    Une seule transaction enchaîne : la réapplication des épinglages posés par l'administration, la réinitialisation des attributions dérivées, le rattachement des signatures aux personnes connues, la création des personnes pour les signatures restantes, la régénération des formes de nom, puis la purge des formes devenues ambiguës et des personnes vidées. Les publications hors scope sont écartées (`domain/publications/scope`).
    """
    from pipeline.transformation.persons.matching import PersonsMatchingQueries
    from pipeline.transformation.persons.name_forms import PersonNameFormsQueries

    return PersonsPhase(
        PersonsMatchingQueries(),
        PersonNameFormsQueries(),
        writes_factory=PersonWrites,
        orphans_log=setup_file_logger("persons_orphelines", str(PROJECT_ROOT / "logs")),
    )
