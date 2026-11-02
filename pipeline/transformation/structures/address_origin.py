"""Tâche `affiliations.classify_addresses` : origine du texte des adresses sans origine (`addresses.origin`)."""

import json
import logging
from collections import Counter

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.structures.address_origin import AddressOrigin, address_origin
from infrastructure.db.scalars import scalar_int
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.countries.country_names import load_country_names

# Adresses par tranche : la taille borne la mémoire et le nombre d'allers-retours SQL.
CHUNK_SIZE = 10_000

_COUNT_UNCLASSIFIED = text("SELECT count(*) FROM addresses WHERE origin IS NULL")

_FETCH_UNCLASSIFIED = text("""
    SELECT id, raw_text, normalized_text FROM addresses
    WHERE origin IS NULL AND id > :after
    ORDER BY id LIMIT :limit
""")

_UPDATE_ORIGINS = text("""
    UPDATE addresses a SET origin = CAST(t.origin AS address_origin)
    FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS t(id integer, origin text)
    WHERE a.id = t.id
""")


def load_structure_names(conn: Connection) -> frozenset[str]:
    """Renvoie les noms normalisés des structures HAL et des organisations ROR."""
    names = conn.execute(
        text("SELECT name FROM hal_structures UNION SELECT name FROM ror_organizations")
    ).scalars()
    return frozenset(normalize_text(name) for name in names)


def classify_addresses(
    conn: Connection, logger: logging.Logger, *, chunk_size: int = CHUNK_SIZE
) -> PhaseMetrics:
    """Pose l'origine du texte des adresses sans origine, tranche par tranche. L'appelant commite."""
    total = scalar_int(conn.execute(_COUNT_UNCLASSIFIED))
    if not total:
        nothing_to_do(logger)
        return PhaseMetrics()

    structure_names = load_structure_names(conn)
    country_names = load_country_names(conn)
    counts: Counter[AddressOrigin] = Counter()
    after_id = 0
    with track_progress(total, BRANCH.rstrip(), logger) as progress:
        while rows := conn.execute(
            _FETCH_UNCLASSIFIED, {"after": after_id, "limit": chunk_size}
        ).all():
            after_id = rows[-1].id
            origins = [
                (
                    r.id,
                    address_origin(
                        r.raw_text,
                        r.normalized_text,
                        structure_names=structure_names,
                        country_names=country_names,
                    ),
                )
                for r in rows
            ]
            payload = [{"id": address_id, "origin": origin.value} for address_id, origin in origins]
            conn.execute(_UPDATE_ORIGINS, {"payload": json.dumps(payload)})
            counts.update(origin for _, origin in origins)
            progress.advance(len(rows))

    classified = counts.total()
    logger.info(
        "%s%s %s : %s, %s, %s",
        LAST_BRANCH,
        quantity(classified, "adresse"),
        inflect(classified, "classée"),
        quantity(counts[AddressOrigin.RAW], "adresse brute", "adresses brutes"),
        quantity(counts[AddressOrigin.HAL_LABEL], "libellé HAL", "libellés HAL"),
        quantity(counts[AddressOrigin.NAME_ONLY], "nom seul", "noms seuls"),
    )
    return PhaseMetrics(seen=classified, updated=classified)
