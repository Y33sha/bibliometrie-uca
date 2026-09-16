"""Sous-étape de la phase `publishers_journals` — vérifie les ISSN des revues dans le Sudoc.

Sont reprises les revues jamais vérifiées qui portent un ISSN, valide ou rejeté, et les revues dont un enregistrement porte un ISSN absent de leurs ISSN. Le Sudoc donne la notice de chacun de leurs ISSN, des corrections possibles de leurs ISSN rejetés fautifs, et des ISSN d'autre support que ces notices désignent. `domain.journals.issn_check` en tire les ISSN à mettre parmi les rejetés, à corriger et à ranger. La revue est ensuite marquée vérifiée.

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
    SetAsideReason,
    SudocCheck,
    check_journal_issns,
    correction_candidates,
)
from domain.sources.sudoc import SudocSerialRecord, Support

COMMIT_EVERY = 50  # revues par commit

FetchPpns = Callable[[httpx2.AsyncClient, Sequence[str]], Awaitable[dict[str, tuple[str, ...]]]]
"""`(client, issns) -> {issn: ppns}` : PPN des notices Sudoc de chaque ISSN connu du Sudoc."""

FetchRecord = Callable[[httpx2.AsyncClient, str], Awaitable[SudocSerialRecord | None]]
"""`(client, ppn) -> notice`, ou `None` si la notice est introuvable ou illisible."""

_SUPPORT_LABELS = {Support.PRINT: "papier", Support.ELECTRONIC: "en ligne"}

# Le sort des ISSN d'une revue tient du détail : le terminal le masque, le journal le garde.
_DETAIL = {"detail": True}


def _journal_issns(row: JournalSudocRow) -> JournalIssns:
    return JournalIssns(
        row.title, row.issn, row.eissn, row.issnl, row.rejected_issns, row.document_issns
    )


def _adopted(row: JournalSudocRow, check: SudocCheck) -> tuple[str, ...]:
    """ISSN venus des enregistrements de la revue que la vérification range dans une de ses colonnes."""
    return tuple(i for i in row.document_issns if i in (check.issn, check.eissn, check.issnl))


def _log_check(logger: logging.Logger, row: JournalSudocRow, check: SudocCheck) -> None:
    label = f"Revue {row.id} ({row.title!r})"
    for issn in _adopted(row, check):
        logger.info(
            "%s : ISSN %s d'un enregistrement ajouté à la revue", label, issn, extra=_DETAIL
        )
    if check.conflict:
        logger.warning(
            "%s : ISSN de deux publications à égalité — laissés en l'état", label, extra=_DETAIL
        )
    for issn, reason in check.set_aside:
        # Un ISSN d'une autre publication trahit une erreur de source : il est signalé en avertissement.
        level = logging.WARNING if reason is SetAsideReason.OTHER_PUBLICATION else logging.INFO
        logger.log(
            level,
            "%s : ISSN %s rangé parmi les ISSN rejetés (%s)",
            label,
            issn,
            reason,
            extra=_DETAIL,
        )
    for raw, corrected in check.corrections:
        logger.info("%s : ISSN rejeté %r corrigé en %s", label, raw, corrected, extra=_DETAIL)
    if check.ambiguous_support is not None:
        logger.warning(
            "%s : plusieurs ISSN %s — laissés dans leurs colonnes",
            label,
            _SUPPORT_LABELS.get(check.ambiguous_support, check.ambiguous_support),
            extra=_DETAIL,
        )


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

    async def _read(
        client: httpx2.AsyncClient, issns: Sequence[str], records: dict[str, SudocSerialRecord]
    ) -> None:
        """Ajoute à `records` la notice de chaque ISSN connu du Sudoc. `record_by_ppn` garde les notices déjà lues."""
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

    async def _fetch(
        client: httpx2.AsyncClient, row: JournalSudocRow
    ) -> dict[str, SudocSerialRecord] | None:
        """Notices utiles à la vérification de la revue, ou `None` si une requête a échoué."""
        journal = _journal_issns(row)
        issns = (*journal.examined(), *correction_candidates(journal.rejected))
        records: dict[str, SudocSerialRecord] = {}
        try:
            await _read(client, issns, records)
            # L'ISSN d'autre support qu'une notice désigne complète une colonne vide : sa propre notice donne son support.
            others = list(
                dict.fromkeys(
                    x for r in records.values() for x in r.other_support_issns if x not in issns
                )
            )
            if others:
                await _read(client, others, records)
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
                issn_set_aside=len(check.set_aside),
                issn_corrected=len(check.corrections),
                issn_conflicts=int(check.conflict),
                issn_unranged=int(check.ambiguous_support is not None),
                issn_from_documents=len(_adopted(row, check)),
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
