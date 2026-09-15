"""Sous-étape de la phase `publishers_journals` — vérifie les ISSN des revues dans le Sudoc.

Sont reprises les revues jamais vérifiées qui portent un ISSN, valide ou rejeté. Le Sudoc donne la notice de chacun de leurs ISSN et des corrections possibles de leurs ISSN rejetés. `domain.journals.issn_check` en tire les ISSN à retirer, à corriger et à ranger. La revue est ensuite marquée vérifiée.

Le fetch Sudoc et le circuit-breaker de source sont injectés (le HTTP vit dans `infrastructure/sources/sudoc`).
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.journals import JournalSudocQueries, JournalSudocRow
from domain.journals.issn_check import (
    JournalIssns,
    SudocCheck,
    check_journal_issns,
    correction_candidates,
)
from domain.sources.sudoc import SudocSerialRecord

BATCH_SIZE = 50  # revues par lot

FetchPpns = Callable[[Sequence[str]], dict[str, tuple[str, ...]]]
"""`(issns) -> {issn: ppns}` : PPN des notices Sudoc de chaque ISSN connu du Sudoc."""

FetchRecord = Callable[[str], SudocSerialRecord | None]
"""`(ppn) -> notice`, ou `None` si la notice est introuvable ou illisible."""


def _journal_issns(row: JournalSudocRow) -> JournalIssns:
    return JournalIssns(row.title, row.issn, row.eissn, row.issnl, row.rejected_issns)


def _log_check(logger: logging.Logger, row: JournalSudocRow, check: SudocCheck) -> None:
    label = f"Revue {row.id} ({row.title!r})"
    if check.conflict:
        logger.warning("%s : ISSN d'ISSN-L différents, à égalité — laissés en l'état", label)
    for issn in check.intruders:
        logger.warning("%s : ISSN %s retiré, son ISSN-L diffère de celui de la revue", label, issn)
    for raw, corrected in check.corrections:
        logger.info("%s : ISSN rejeté %r corrigé en %s", label, raw, corrected)
    if check.ambiguous_support:
        logger.warning("%s : ISSN non rangés par support (plusieurs ISSN d'un même support)", label)


def run_check_journals_in_sudoc(
    conn: Connection,
    logger: logging.Logger,
    *,
    journal_repo: JournalSudocQueries,
    fetch_ppns: FetchPpns,
    fetch_record: FetchRecord,
    breaker: CircuitBreaker,
) -> PhaseMetrics:
    rows = journal_repo.find_journals_to_check_in_sudoc()
    total = len(rows)
    metrics = PhaseMetrics()
    if total == 0:
        return metrics
    metrics.add(total=total)
    etape(
        logger,
        "%s : vérification des ISSN dans le Sudoc",
        accord(total, "revue à vérifier", "revues à vérifier"),
    )

    record_by_ppn: dict[str, SudocSerialRecord | None] = {}
    processed = 0
    # Le compteur de la barre porte les revues présentes dans le Sudoc.
    with progression(total, BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:
        for i in range(0, total, BATCH_SIZE):
            if breaker.tripped:
                logger.warning(
                    "⚡ Coupe-circuit Sudoc : vérification interrompue à %d/%d, reste repris au prochain run.",
                    processed,
                    total,
                )
                break
            batch = [(row, _journal_issns(row)) for row in rows[i : i + BATCH_SIZE]]
            wanted = {issn for _, journal in batch for issn in journal.own()}
            wanted |= {c for _, journal in batch for c in correction_candidates(journal.rejected)}
            records: dict[str, SudocSerialRecord] = {}
            for issn, ppns in fetch_ppns(sorted(wanted)).items():
                ppn = ppns[0]
                if ppn not in record_by_ppn:
                    record_by_ppn[ppn] = fetch_record(ppn)
                if (record := record_by_ppn[ppn]) is not None:
                    records[issn] = record

            checked_at = datetime.now(UTC)
            for row, journal in batch:
                check = check_journal_issns(journal, records)
                _log_check(logger, row, check)
                journal_repo.record_sudoc_check(
                    row.id,
                    issn=check.issn,
                    eissn=check.eissn,
                    issnl=check.issnl,
                    rejected_issns=check.rejected,
                    checked_at=checked_at,
                )
                changed = (check.issn, check.eissn, check.issnl, check.rejected) != (
                    row.issn,
                    row.eissn,
                    row.issnl,
                    row.rejected_issns,
                )
                metrics.add(
                    updated=int(changed),
                    unchanged=int(not changed),
                    sudoc_found=int(check.found),
                    issn_removed=len(check.intruders),
                    issn_corrected=len(check.corrections),
                    issnl_conflicts=int(check.conflict),
                    issn_unranged=int(check.ambiguous_support),
                )
                processed += 1
                avancement.avance()
                avancement.retient(int(check.found))
            conn.commit()

    logger.info(
        "%sTerminé : %d/%d %s vérifiées, %d présentes dans le Sudoc, %d modifiées",
        DERNIERE_BRANCHE,
        processed,
        total,
        forme(total, "revue"),
        metrics.extras.get("sudoc_found", 0),
        metrics.updated,
    )
    return metrics
