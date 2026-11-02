"""Tâche `affiliations.classify_addresses` : origine du texte des adresses sans origine (`addresses.origin`)."""

import json
import logging
from collections import Counter

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.structures.address_origin import AddressOrigin, address_origin
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, nothing_to_do, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.countries.country_names import load_country_names

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


def classify_addresses(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Pose l'origine du texte des adresses sans origine. L'appelant commite."""
    rows = conn.execute(
        text("SELECT id, raw_text, normalized_text FROM addresses WHERE origin IS NULL")
    ).all()
    if not rows:
        nothing_to_do(logger)
        return PhaseMetrics()

    structure_names = load_structure_names(conn)
    country_names = load_country_names(conn)
    origins = {
        r.id: address_origin(
            r.raw_text,
            r.normalized_text,
            structure_names=structure_names,
            country_names=country_names,
        )
        for r in rows
    }
    payload = [{"id": address_id, "origin": origin.value} for address_id, origin in origins.items()]
    conn.execute(_UPDATE_ORIGINS, {"payload": json.dumps(payload)})

    counts = Counter(origins.values())
    logger.info(
        "%s%s %s : %s, %s, %s",
        LAST_BRANCH,
        quantity(len(rows), "adresse"),
        inflect(len(rows), "classée"),
        quantity(counts[AddressOrigin.RAW], "adresse brute", "adresses brutes"),
        quantity(counts[AddressOrigin.HAL_LABEL], "libellé HAL", "libellés HAL"),
        quantity(counts[AddressOrigin.NAME_ONLY], "nom seul", "noms seuls"),
    )
    return PhaseMetrics(seen=len(rows), updated=len(rows))
