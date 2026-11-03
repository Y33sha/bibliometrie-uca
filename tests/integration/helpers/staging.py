"""Semis des tables du moissonnage, sur la connexion SQLAlchemy (`sa_sync_conn`) : lignes de staging et recherches infructueuses (`failed_lookups`)."""

import json
import logging

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.staging import StagingStore
from tests.integration.helpers.queues import mark


def insert_staging(
    conn: Connection,
    source: str = "hal",
    *,
    source_id: str,
    raw_data: object = None,
    doi: str | None = None,
    queued: bool = True,
    raw_hash: str | None = None,
    seen_days_ago: int | None = None,
    disappeared: bool = False,
    replace: bool = False,
) -> int:
    """Insère une ligne de staging et renvoie son `id`.

    `raw_data` vaut `{}` par défaut. `queued` met la ligne en file de normalisation, comme un document moissonné. `seen_days_ago` recule `last_seen_at` d'autant de jours avant l'instant de la transaction ; `disappeared` date la disparition de cet instant. Une colonne laissée à `None` prend la valeur par défaut du schéma. `replace` réécrit le contenu d'une ligne (source, source_id) existante.
    """
    values = {
        "source": source,
        "source_id": source_id,
        "doi": doi,
        "raw_data": json.dumps(raw_data if raw_data is not None else {}),
        "raw_hash": raw_hash,
    }
    expressions = {
        "source": "CAST(:source AS source_type)",
        "raw_data": "CAST(:raw_data AS jsonb)",
    }
    if seen_days_ago is not None:
        values["seen_days_ago"] = seen_days_ago
        expressions["last_seen_at"] = "now() - make_interval(days => :seen_days_ago)"
    if disappeared:
        expressions["disappeared_at"] = "now()"
    columns = [
        column
        for column, value in values.items()
        if value is not None and column != "seen_days_ago"
    ]
    columns += [column for column in expressions if column not in values]
    placeholders = [expressions.get(column, f":{column}") for column in columns]
    conflict = (
        " ON CONFLICT (source, source_id) DO UPDATE SET raw_data = EXCLUDED.raw_data"
        if replace
        else ""
    )
    staging_id = conn.execute(
        text(
            f"INSERT INTO staging ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            f"{conflict} RETURNING id"
        ),
        {column: value for column, value in values.items() if value is not None},
    ).scalar_one()
    if queued:
        mark(conn, Queue.STAGING_NORMALIZATION, [staging_id])
    return staging_id


def insert_failed_lookup(
    conn: Connection,
    source: str = "hal",
    *,
    id_type: str,
    id_value: str,
    not_found_days_ago: int = 0,
) -> None:
    """Inscrit une recherche infructueuse de `id_value`, datée de `not_found_days_ago` jours avant l'instant de la transaction."""
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at) "
            "VALUES (CAST(:source AS lookup_source), :id_type, :id_value, "
            "now() - make_interval(days => :ago))"
        ),
        {"source": source, "id_type": id_type, "id_value": id_value, "ago": not_found_days_ago},
    )


def normalize_pending(conn: Connection, source: str) -> int:
    """Normalise les lignes de `source` en file, avec le normaliseur de la phase, dans la transaction du test, puis les retire de la file. Renvoie le nombre d'enregistrements sources normalisés."""
    normalizer = normalizer_builders(archive=False)[source](conn, logging.getLogger("test"))
    store = StagingStore(conn)
    ids = store.snapshot_pending(source)
    normalized = sum(1 for row in store.fetch_staging_by_ids(ids) if normalizer.process_work(row))
    store.forget_normalized(ids)
    return normalized
