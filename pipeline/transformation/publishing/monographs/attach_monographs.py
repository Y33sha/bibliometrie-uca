"""Sous-étape de la phase `publishing` : rattachement des enregistrements sources à leur monographie.

Le rattachement se calcule sur tous les enregistrements sources qui décrivent un volume (`biblio.monograph`), selon `domain.monographs.attachment`. Chaque volume reprend sa monographie existante. Plusieurs monographies existantes d'un même volume fusionnent dans la plus ancienne. Un volume sans monographie existante en crée une. La monographie reçoit les champs qui lui manquent. Un enregistrement source hors de tout volume perd sa monographie. Un enregistrement source qui change de monographie est marqué pour la réconciliation.
"""

import json
import logging

from sqlalchemy import Connection, text

from domain.monographs.attachment import Volume, VolumeRecord, group_volumes
from domain.normalize import normalize_text
from domain.source_records.biblio import monograph_volume
from infrastructure.db.queues import Queue, enqueue
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.monographs.monograph_merge import merge_monograph_into
from pipeline.transformation.publishing.monographs.store import MonographStore

LABEL = "Rattachement des enregistrements sources aux monographies"
"""Libellé de la sous-étape dans le journal de la phase."""

_RECORDS = text("""
    SELECT id, monograph_id, publisher_id, biblio->'monograph' AS monograph
    FROM source_records
    WHERE biblio ? 'monograph' OR monograph_id IS NOT NULL
""")

_SET_MONOGRAPHS = text("""
    UPDATE source_records sr SET monograph_id = t.monograph_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, monograph_id integer)
    WHERE sr.id = t.id
""")


def _volume_records(conn: Connection) -> tuple[list[VolumeRecord], dict[int, int | None]]:
    """Renvoie les enregistrements sources qui décrivent un volume, et la monographie actuelle de chaque enregistrement source lu."""
    records: list[VolumeRecord] = []
    current: dict[int, int | None] = {}
    for r in conn.execute(_RECORDS):
        current[r.id] = r.monograph_id
        volume = monograph_volume({"monograph": r.monograph})
        if volume is not None:
            records.append(
                VolumeRecord(
                    r.id,
                    volume.title,
                    volume.isbns,
                    volume.eisbns,
                    volume.proceedings,
                    volume.year,
                    r.publisher_id,
                )
            )
    return records, current


def _monograph_of(store: MonographStore, conn: Connection, volume: Volume) -> tuple[int, bool]:
    """Renvoie la monographie du volume et vrai si elle est créée. Les autres monographies existantes du volume fusionnent dans la première, qui reçoit ensuite les champs manquants."""
    if volume.monograph_ids:
        target, *others = volume.monograph_ids
        for other in others:
            merge_monograph_into(conn, target, other)
        store.enrich_monograph(
            target,
            proceedings=volume.proceedings,
            year=volume.year,
            isbn=volume.isbn,
            eisbn=volume.eisbn,
            publisher_id=volume.publisher_id,
        )
        return target, False
    assert volume.title, "garanti par `group_volumes`"
    created = store.create_monograph(
        title=volume.title,
        title_normalized=normalize_text(volume.title),
        proceedings=volume.proceedings,
        year=volume.year,
        isbn=volume.isbn,
        eisbn=volume.eisbn,
        publisher_id=volume.publisher_id,
    )
    return created, True


def run_attach_monographs(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Rattache les enregistrements sources à leur monographie et renvoie les compteurs."""
    store = MonographStore(conn)
    records, current = _volume_records(conn)
    volumes = group_volumes(records, store.existing_monographs())
    desired: dict[int, int | None] = dict.fromkeys(current)
    created = merged = 0
    for volume in volumes:
        monograph_id, is_new = _monograph_of(store, conn, volume)
        created += is_new
        merged += max(len(volume.monograph_ids) - 1, 0)
        desired |= dict.fromkeys(volume.record_ids, monograph_id)
    changed = [
        {"id": record_id, "monograph_id": monograph_id}
        for record_id, monograph_id in desired.items()
        if monograph_id != current.get(record_id)
    ]
    if changed:
        conn.execute(_SET_MONOGRAPHS, {"rows": json.dumps(changed)})
        enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT unnest(CAST(:ids AS integer[]))",
            {"ids": [row["id"] for row in changed]},
        )
    detached = sum(row["monograph_id"] is None for row in changed)
    metrics = PhaseMetrics()
    metrics.add(
        seen=len(desired),
        updated=len(changed) - detached,
        monographs_created=created,
        monographs_merged=merged,
        monographs_detached=detached,
    )
    metrics.report = (
        f"{quantity(len(changed) - detached, 'enregistrement source rattaché', 'enregistrements sources rattachés')}, "
        f"{quantity(detached, 'détaché', 'détachés')}, "
        f"{quantity(created, 'monographie créée', 'monographies créées')}, "
        f"{quantity(merged, 'monographie fusionnée', 'monographies fusionnées')}"
    )
    return metrics
