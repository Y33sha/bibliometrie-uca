"""Semis des tables d'extraction, sur la connexion SQLAlchemy (`sa_sync_conn`) : lignes de staging et recherches infructueuses (`failed_lookups`)."""

import json
import logging

from sqlalchemy import Connection, text

from pipeline.ingestion.common.normalize import _normalize_builders
from pipeline.ingestion.common.staging import StagingStore

# Colonnes remises à jour quand la ligne (source, source_id) existe déjà.
_UPSERTS = {
    "processed": "processed = FALSE",
    "raw_data": "processed = FALSE, raw_data = EXCLUDED.raw_data",
}


def insert_staging(
    conn: Connection,
    source: str = "hal",
    *,
    source_id: str,
    raw_data: object = None,
    doi: str | None = None,
    processed: bool | None = None,
    raw_hash: str | None = None,
    seen_days_ago: int | None = None,
    disappeared: bool = False,
    upsert: str | None = None,
) -> int:
    """Insère une ligne de staging et renvoie son `id`.

    `raw_data` vaut `{}` par défaut. `seen_days_ago` recule `last_seen_at` d'autant de jours avant l'instant de la transaction ; `disappeared` date la disparition de cet instant. Une colonne laissée à `None` prend la valeur par défaut du schéma. Sur une ligne (source, source_id) existante, `upsert="processed"` la remet à traiter et `upsert="raw_data"` remplace aussi son contenu.
    """
    values = {
        "source": source,
        "source_id": source_id,
        "doi": doi,
        "raw_data": json.dumps(raw_data if raw_data is not None else {}),
        "processed": processed,
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
        f" ON CONFLICT (source, source_id) DO UPDATE SET {_UPSERTS[upsert]}" if upsert else ""
    )
    return conn.execute(
        text(
            f"INSERT INTO staging ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            f"{conflict} RETURNING id"
        ),
        {column: value for column, value in values.items() if value is not None},
    ).scalar_one()


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
    """Normalise les lignes de staging à traiter de `source`, avec le normaliseur de la phase, dans la transaction du test. Rend le nombre d'enregistrements sources normalisés."""
    normalizer = _normalize_builders(archive=False)[source](conn, logging.getLogger("test"))
    rows = StagingStore(conn).fetch_pending_staging(source, limit=10_000)
    return sum(1 for row in rows if normalizer.process_work(row))
