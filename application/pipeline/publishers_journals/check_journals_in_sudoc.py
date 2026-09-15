"""Sous-étape de la phase `publishers_journals` — vérifie les ISSN des revues dans le Sudoc.

Sont reprises les revues jamais vérifiées qui portent un ISSN, valide ou rejeté. Le Sudoc donne la notice de chacun de leurs ISSN et des corrections possibles de leurs ISSN rejetés. `domain.journals.issn_check` en tire les ISSN à retirer, à corriger et à ranger. La revue est ensuite marquée vérifiée.

Les revues passent par `run_fetch_pool` : téléchargements concurrents sur un client HTTP partagé, écritures sérialisées, commit par paquets. Un rythme commun (`RequestPace`) plafonne le débit, toutes requêtes simultanées confondues. Une revue dont une requête échoue n'est pas marquée vérifiée : le run suivant la reprend. Le fetch Sudoc et le circuit-breaker de source sont injectés (le HTTP vit dans `infrastructure/sources/sudoc`).
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import httpx2
from sqlalchemy import Connection

from application.pipeline._fetch_pool import RequestPace, run_fetch_pool
from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.circuit_breaker import CircuitBreaker, SourceUnavailableError
from application.ports.pipeline.journals import JournalSudocQueries, JournalSudocRow
from domain.journals.issn_check import (
    JournalIssns,
    SudocCheck,
    check_journal_issns,
    correction_candidates,
)
from domain.sources.sudoc import SudocSerialRecord

COMMIT_EVERY = 50  # revues par commit

FetchPpns = Callable[[httpx2.AsyncClient, Sequence[str]], Awaitable[dict[str, tuple[str, ...]]]]
"""`(client, issns) -> {issn: ppns}` : PPN des notices Sudoc de chaque ISSN connu du Sudoc."""

FetchRecord = Callable[[httpx2.AsyncClient, str], Awaitable[SudocSerialRecord | None]]
"""`(client, ppn) -> notice`, ou `None` si la notice est introuvable ou illisible."""


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


async def run_check_journals_in_sudoc(
    conn: Connection,
    logger: logging.Logger,
    *,
    journal_repo: JournalSudocQueries,
    fetch_ppns: FetchPpns,
    fetch_record: FetchRecord,
    breaker: CircuitBreaker,
    max_concurrent: int,
    max_per_second: float,
) -> PhaseMetrics:
    """Vérifie les revues à vérifier, `max_concurrent` à la fois, à `max_per_second` requêtes par seconde au plus."""
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
    pace = RequestPace(max_per_second)

    async def _fetch(
        client: httpx2.AsyncClient, row: JournalSudocRow
    ) -> dict[str, SudocSerialRecord] | None:
        """Notices des ISSN de la revue et des corrections de ses ISSN rejetés, ou `None` si une requête a échoué."""
        journal = _journal_issns(row)
        issns = (*journal.own(), *correction_candidates(journal.rejected))
        records: dict[str, SudocSerialRecord] = {}
        try:
            await pace.wait()
            ppns_by_issn = await fetch_ppns(client, issns)
            for issn in issns:
                if not (ppns := ppns_by_issn.get(issn)):
                    continue
                if ppns[0] not in record_by_ppn:
                    await pace.wait()
                    record_by_ppn[ppns[0]] = await fetch_record(client, ppns[0])
                if (record := record_by_ppn[ppns[0]]) is not None:
                    records[issn] = record
        except (httpx2.HTTPError, SourceUnavailableError) as exc:
            logger.warning(
                "Revue %d : requête Sudoc en échec, reprise au prochain run (%s)", row.id, exc
            )
            return None
        return records

    # Le compteur de la barre porte les revues présentes dans le Sudoc.
    with progression(total, BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:

        def _write(
            conn: Connection, row: JournalSudocRow, records: dict[str, SudocSerialRecord] | None
        ) -> None:
            avancement.avance()
            if records is None:
                metrics.add(errors=1)
                return
            check = check_journal_issns(_journal_issns(row), records)
            _log_check(logger, row, check)
            journal_repo.record_sudoc_check(
                row.id,
                issn=check.issn,
                eissn=check.eissn,
                issnl=check.issnl,
                rejected_issns=check.rejected,
                checked_at=datetime.now(UTC),
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
            avancement.retient(int(check.found))

        await run_fetch_pool(
            rows,
            conn,
            max_concurrent=max_concurrent,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
            should_continue=lambda: not breaker.tripped,
        )

    checked = metrics.updated + metrics.unchanged
    if breaker.tripped:
        logger.warning(
            "⚡ Coupe-circuit Sudoc : vérification interrompue à %d/%d, reste repris au prochain run.",
            checked,
            total,
        )
    logger.info(
        "%sTerminé : %d/%d %s vérifiées, %d présentes dans le Sudoc, %d modifiées",
        DERNIERE_BRANCHE,
        checked,
        total,
        forme(total, "revue"),
        metrics.extras.get("sudoc_found", 0),
        metrics.updated,
    )
    return metrics
