"""Phase `open_access` : verdict d'Unpaywall sur le DOI des publications, puis statut open access des publications.

`verify_unpaywall` (`pipeline.transformation.dois.lookups`) interroge Unpaywall sur les DOI jamais interrogés ou périmés. `recompute_oa_status` recalcule ensuite le statut open access de chaque publication (`oa_inputs`), et écrit les statuts qui changent : verdict d'Unpaywall, embargo échu, modèle open access de la revue.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence

from sqlalchemy import Connection, Row, text

from pipeline.graph import Block, Phase, Task, in_transaction
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.dois import lookups
from pipeline.transformation.publications.oa_inputs import OaFacts, oa_inputs

BATCH_SIZE = 5000
"""Publications par lot : la taille borne la mémoire et le nombre d'allers-retours SQL."""

_PUBLICATIONS = text("""
    SELECT id, doi, serial_id, doc_type::text AS doc_type, source_extras, oa_status::text AS oa_status
    FROM publications
    ORDER BY id
""")

_WRITE_STATUSES = text("""
    UPDATE publications p SET oa_status = CAST(t.status AS oa_type)
    FROM unnest(CAST(:ids AS integer[]), CAST(:statuses AS text[])) AS t(id, status)
    WHERE p.id = t.id
""")


def _statuses(conn: Connection, rows: Sequence[Row[tuple[object, ...]]]) -> dict[int, str]:
    """Renvoie le statut open access calculé de chaque publication du lot."""
    inputs = oa_inputs(
        conn,
        [OaFacts(r.id, r.doi, r.serial_id, r.doc_type, r.source_extras) for r in rows],
    )
    return {r.id: str(inputs[r.id].status()) for r in rows}


def recompute_oa_status(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Recalcule le statut open access de chaque publication et écrit les statuts qui changent. Le bilan donne, par statut, le nombre de publications et sa variation."""
    rows = conn.execute(_PUBLICATIONS).all()
    before: Counter[str] = Counter(str(r.oa_status) for r in rows)
    after: Counter[str] = Counter()
    changed: dict[int, str] = {}
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        computed = _statuses(conn, batch)
        after.update(computed.values())
        changed |= {r.id: computed[r.id] for r in batch if computed[r.id] != r.oa_status}
    if changed:
        conn.execute(_WRITE_STATUSES, {"ids": list(changed), "statuses": list(changed.values())})
    metrics = PhaseMetrics(seen=len(rows), updated=len(changed))
    metrics.report = quantity(len(changed), "statut modifié", "statuts modifiés")
    metrics.details["table"] = {
        "rows": [
            {"key": status, "count": after[status], "delta": after[status] - before[status]}
            for status in sorted(after.keys() | before.keys(), key=lambda s: -after[s])
        ]
    }
    return metrics


RECOMPUTE_OA_STATUS = Task(
    "recompute_oa_status",
    reads=(
        "publications.id",
        "publications.doi",
        "publications.serial_id",
        "publications.doc_type",
        "publications.source_extras",
        "publications.oa_status",
        "serials.oa_model",
        "dois.unpaywall_oa_status",
        "dois.registered_url",
        "embargoes",
        "source_records",
        "source_record_locations",
        "platforms",
    ),
    writes=("publications.oa_status",),
    run=in_transaction(recompute_oa_status),
    section="Statut open access des publications",
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : interrogation d'Unpaywall (`services`) et statuts open access (`table`)."""
    metrics = lookups.assemble({"verify_unpaywall": by_task["verify_unpaywall"]})
    metrics.details["table"] = by_task["recompute_oa_status"].details["table"]
    return metrics


PHASE = Phase(
    "open_access",
    "Statut open access des publications",
    (lookups.VERIFY_UNPAYWALL, RECOMPUTE_OA_STATUS),
    Block.DERIVED_DATA,
    assemble=assemble,
)
