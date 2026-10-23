"""Sous-étape de la phase `publishers_journals` — enrichit les revues à partir de l'API OpenAlex Sources.

Champs mis à jour :
- `apc_amount`, `apc_currency` (prix catalogue DOAJ exposés par OpenAlex)
- `journal_type` (via le mapping local du `type` OpenAlex), uniquement quand le mapping renvoie une valeur exploitable

Le fetch OpenAlex est injecté (le HTTP vit dans `pipeline/ingestion/openalex`). L'orchestrateur s'arrête quand le circuit-breaker de la source coupe. Appelé par `run_pipeline`.
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection, any_, func, literal, select, update

from domain.journals.journal import JournalType, ManualField
from infrastructure.db.tables import journals
from pipeline.http.circuit_breaker import source_tripped
from pipeline.runtime.observability.log_format import inflect
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.journals.store import JournalStore

LABEL = "Type des revues sur OpenAlex"
"""Libellé de la sous-étape dans le journal de la phase."""

BATCH_SIZE = 50
COMMIT_EVERY = 500  # commit DB tous les N journals traités


# L'APC n'est pas saisi à la main : le pipeline peut l'écrire.
_APC_NOT_MANUAL = ~(literal(ManualField.APC.value) == any_(journals.c.manual_fields))


def find_journals_of_unknown_type(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """`(id, openalex_id)` des revues au `journal_type` indéterminé qui ont un `openalex_id`, à typer via OpenAlex. Le type étant stable par revue, une revue typée sort de la file. `limit` cape le run."""
    rows = conn.execute(
        select(journals.c.id, journals.c.openalex_id)
        .where(journals.c.openalex_id.is_not(None))
        .where(journals.c.journal_type == "unknown")
        .order_by(journals.c.id)
        .limit(limit or None)
    ).all()
    return [(r.id, r.openalex_id) for r in rows]


def update_journal_apc(
    conn: Connection,
    journal_id: int,
    *,
    apc_amount: float | None = None,
    apc_currency: str | None = None,
) -> None:
    """Met à jour le montant et la devise d'APC. COALESCE : un argument `None` laisse la valeur en place."""
    conn.execute(
        update(journals)
        .where(journals.c.id == journal_id, _APC_NOT_MANUAL)
        .values(
            apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
            apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
        )
    )


_OPENALEX_SOURCE_TYPE_MAP: dict[str, JournalType] = {
    "journal": JournalType.JOURNAL,
    "repository": JournalType.REPOSITORY,
    "conference": JournalType.PROCEEDINGS,
    "book series": JournalType.BOOK_SERIES,
    "ebook platform": JournalType.EBOOK_PLATFORM,
}


def map_openalex_source_type(raw: str | None) -> JournalType | None:
    """Mappe le champ `type` d'une source OpenAlex vers l'enum `journal_type`, ou `None` pour les types sans signal exploitable (`metadata`, `other`) et les types inconnus.

    `preprint_server` et `media` sont absents de la table (sans équivalent dans la taxonomie OpenAlex) et restent posés à la main.
    """
    if not raw:
        return None
    return _OPENALEX_SOURCE_TYPE_MAP.get(raw.lower())


FetchSourcesBatch = Callable[[list[str]], dict[str, tuple[float | None, str | None, str | None]]]
"""Signature du fetch injecté : `(openalex_ids) -> {short_id: (apc_amount, apc_currency, raw_type)}`."""


def run_enrich_journals_from_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_batch: FetchSourcesBatch,
) -> PhaseMetrics:
    store = JournalStore(conn)
    pending = find_journals_of_unknown_type(conn)
    total = len(pending)
    if total == 0:
        return PhaseMetrics()

    updated = 0
    with_apc = 0
    processed = 0
    type_written = 0

    for i in range(0, total, BATCH_SIZE):
        if source_tripped():
            conn.commit()
            logger.warning(
                "⚡ Coupe-circuit OpenAlex : enrichissement revues interrompu à %d/%d, reste retenté au prochain run.",
                processed,
                total,
            )
            return _summary(total, updated)

        id_map = {row[1]: row[0] for row in pending[i : i + BATCH_SIZE]}
        sources = fetch_batch(list(id_map))

        for oa_id, journal_id in id_map.items():
            data = sources.get(oa_id)
            if data is None:
                processed += 1
                continue
            apc_amount, apc_currency, raw_type = data

            # Sans APC dans OpenAlex, montant et devise de la revue restent tels quels.
            if apc_amount is not None:
                update_journal_apc(
                    conn, journal_id, apc_amount=apc_amount, apc_currency=apc_currency
                )
            # journal_type : seules les revues `unknown` sont traitées (cf. `fetch_journals_of_unknown_type`). On écrit dès que le mapping OpenAlex renvoie une valeur ; une revue au type `metadata`/`other` reste `unknown` et repasse au prochain run.
            mapped_type = map_openalex_source_type(raw_type)
            if mapped_type is not None:
                store.set_journal_type(journal_id, mapped_type)
                type_written += 1

            updated += 1
            if apc_amount is not None:
                with_apc += 1
            processed += 1

        if processed % COMMIT_EVERY < BATCH_SIZE:
            conn.commit()

    conn.commit()
    return _summary(total, updated)


def _summary(total: int, updated: int) -> PhaseMetrics:
    metrics = PhaseMetrics(seen=total, updated=updated)
    metrics.report = (
        f"{updated}/{total} {inflect(total, 'revue mise à jour', 'revues mises à jour')}"
    )
    return metrics
