"""Sous-étape de la phase `publishing` : rattachement des enregistrements sources à leur éditeur.

Le rattachement se calcule sur tous les enregistrements sources qui nomment un éditeur (`biblio.publisher`, `biblio.publisher_openalex_id`), selon `domain.publishers.attachment`. Une production hébergée sans être publiée reste sans éditeur (`source_record_has_publisher`), d'après son type de document d'avant correction et la série ou le volume décrits. Les éditeurs nouveaux sont créés avec leurs formes de nom. Un enregistrement source qui change d'éditeur est marqué pour la réconciliation.
"""

import json
import logging

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.publishers.attachment import (
    NewPublisher,
    PublisherRecord,
    PublisherRef,
    attach_publishers,
)
from domain.publishers.attribution import source_record_has_publisher
from infrastructure.db.queues import Queue, enqueue
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.publishers.store import PublisherStore

LABEL = "Rattachement des enregistrements sources aux éditeurs"
"""Libellé de la sous-étape dans le journal de la phase."""

_RECORDS = text("""
    SELECT id, source, publisher_id,
           COALESCE(corrections->'doc_type'->>'raw', doc_type::text) AS doc_type,
           biblio->>'publisher' AS name,
           biblio->>'publisher_openalex_id' AS openalex_id,
           COALESCE(biblio ? 'journal' OR biblio ? 'monograph', false) AS has_container
    FROM source_records
    WHERE biblio ? 'publisher' OR publisher_id IS NOT NULL
""")

_PUBLISHERS_BY_OPENALEX_ID = text(
    "SELECT openalex_id, id FROM publishers WHERE openalex_id IS NOT NULL"
)

_FORMS = text("SELECT form_normalized, publisher_id FROM publisher_name_forms")

_SET_OPENALEX_ID = text(
    "UPDATE publishers SET openalex_id = :openalex_id WHERE id = :id AND openalex_id IS NULL"
)

_SET_PUBLISHERS = text("""
    UPDATE source_records sr SET publisher_id = t.publisher_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, publisher_id integer)
    WHERE sr.id = t.id
""")


def _publisher_records(conn: Connection) -> tuple[list[PublisherRecord], dict[int, int | None]]:
    """Renvoie les enregistrements sources dont l'éditeur nommé est celui du document, et l'éditeur actuel de chaque enregistrement source lu."""
    records: list[PublisherRecord] = []
    current: dict[int, int | None] = {}
    for r in conn.execute(_RECORDS):
        current[r.id] = r.publisher_id
        if r.name and source_record_has_publisher(
            r.doc_type, r.source, has_container=r.has_container
        ):
            records.append(PublisherRecord(r.id, r.name, r.openalex_id))
    return records, current


def run_attach_publishers(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Rattache les enregistrements sources à leur éditeur et renvoie les compteurs."""
    store = PublisherStore(conn)
    records, current = _publisher_records(conn)
    attachment = attach_publishers(
        records,
        {r.openalex_id: r.id for r in conn.execute(_PUBLISHERS_BY_OPENALEX_ID)},
        {r.form_normalized: r.publisher_id for r in conn.execute(_FORMS)},
    )

    created: dict[NewPublisher, int] = {}

    def resolve(ref: PublisherRef) -> int:
        if isinstance(ref, int):
            return ref
        if ref not in created:
            created[ref] = store.create_publisher(
                name=ref.name, name_normalized=normalize_text(ref.name), openalex_id=ref.openalex_id
            )
        return created[ref]

    for publisher_id, openalex_id in sorted(attachment.openalex_ids.items()):
        conn.execute(_SET_OPENALEX_ID, {"id": publisher_id, "openalex_id": openalex_id})
    for form, ref in sorted(attachment.new_forms.items(), key=lambda item: item[0]):
        store.add_publisher_name_form(resolve(ref), form)
    desired: dict[int, int | None] = dict.fromkeys(current)
    desired |= {
        record_id: resolve(ref) for record_id, ref in sorted(attachment.publisher_of.items())
    }

    changed = [
        {"id": record_id, "publisher_id": publisher_id}
        for record_id, publisher_id in desired.items()
        if publisher_id != current.get(record_id)
    ]
    if changed:
        conn.execute(_SET_PUBLISHERS, {"rows": json.dumps(changed)})
        enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT unnest(CAST(:ids AS integer[]))",
            {"ids": [row["id"] for row in changed]},
        )
    detached = sum(row["publisher_id"] is None for row in changed)
    metrics = PhaseMetrics()
    metrics.add(
        seen=len(desired),
        updated=len(changed) - detached,
        publisher_created=len(created),
        publishers_detached=detached,
    )
    metrics.report = (
        f"{quantity(len(changed) - detached, 'enregistrement source rattaché', 'enregistrements sources rattachés')}, "
        f"{quantity(detached, 'détaché', 'détachés')}, "
        f"{quantity(len(created), 'éditeur créé', 'éditeurs créés')}"
    )
    return metrics
