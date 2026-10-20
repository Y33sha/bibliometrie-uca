# STATUS: oneshot (2026-10-20)
"""Détache les contributions sources rattachées à leur personne par un identifiant rejeté pour cette personne.

Visées : les contributions sources non épinglées résolues par identifiant (`resolution_mode = 'identifier'`), dont les informations du contributeur contiennent un identifiant rejeté pour leur personne, et aucun identifiant non rejeté de cette personne. Leur `person_id` et leur `resolution_mode` passent à NULL. Au run suivant, la phase `persons` les re-résout sans l'identifiant rejeté, et détache les contributions sources cross-source restées sans ancre.

Usage :
    python -m interfaces.cli.oneshot.detach_rejected_identifier_signatures [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.matching import ResolutionMode
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    identifier_neutralized,
    pinned,
)

log = setup_logger("detach_rejected_identifier_signatures", os.path.dirname(__file__))

_REJECTED = AttributionStatus.REJECTED.value

# Contribution source `sc` dont les informations du contributeur `ci` contiennent un identifiant de sa personne, au statut rejeté (`=`) ou non rejeté (`<>`).
_CARRIES_IDENTIFIER = """
    EXISTS (
        SELECT 1 FROM person_identifiers pi
        WHERE pi.person_id = sc.person_id
          AND pi.status {op} '{rejected}'
          AND ci.identifiers ->> pi.id_type::text = pi.id_value
          {extra}
    )
"""

_CARRIES_REJECTED = _CARRIES_IDENTIFIER.format(op="=", rejected=_REJECTED, extra="")
_CARRIES_VALID = _CARRIES_IDENTIFIER.format(
    op="<>", rejected=_REJECTED, extra=f"AND NOT {identifier_neutralized('pi.id_type::text')}"
)

_TARGETS = f"""
    SELECT sc.id
    FROM source_contributions sc
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE sc.resolution_mode = '{ResolutionMode.IDENTIFIER.value}'
      AND {_CARRIES_REJECTED}
      AND NOT {_CARRIES_VALID}
      AND NOT {pinned("sc.id")}
"""

_COUNT_SQL = text(f"""
    SELECT count(*) AS source_contributions, count(DISTINCT sc.person_id) AS personnes
    FROM source_contributions sc WHERE sc.id IN ({_TARGETS})
""")  # noqa: S608 — fragments SQL constants

_DETACH_SQL = text(f"""
    UPDATE source_contributions sc SET {DETACHED_SOURCE_CONTRIBUTION}
    WHERE sc.id IN ({_TARGETS})
""")  # noqa: S608 — fragments SQL constants


def detach(conn: Connection) -> int:
    """Détache les contributions sources visées. Rend le nombre de contributions sources détachées."""
    return conn.execute(_DETACH_SQL).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        counts = conn.execute(_COUNT_SQL).one()
        log.info(
            "contributions sources visées : %d, de %d personnes",
            counts.source_contributions,
            counts.personnes,
        )
        if args.dry_run or not counts.source_contributions:
            conn.rollback()
            return 0
        detached = detach(conn)
        conn.commit()
        log.info("contributions sources détachées : %d", detached)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
