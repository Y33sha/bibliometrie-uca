# STATUS: oneshot (2026-10-02)
"""Attribue aux personnes les idHAL que portent leurs signatures rattachées.

Une valeur d'idHAL portée par une signature rattachée, non neutralisée par elle, et attribuée à aucune personne, est attribuée en `pending` à la personne de la signature, par `add_identifiers_from_authorships`. Une valeur portée par les signatures de plusieurs personnes revient à la première ; l'arbitrage des conflits d'attribution de la phase `persons` la tranche au run suivant.

Usage :
    python -m interfaces.cli.oneshot.backfill_idhal_attributions            # exécution
    python -m interfaces.cli.oneshot.backfill_idhal_attributions --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from application.services.persons.core import add_identifiers_from_authorships
from domain.persons.identifiers import PersonIdentifierType
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.sql_fragments import identifier_neutralized
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("backfill_idhal_attributions", os.path.dirname(__file__))

_IDHAL = PersonIdentifierType.IDHAL.value


def _unattributed(conn: Connection) -> list[tuple[int, str]]:
    """Couples `(person_id, idhal)` des signatures rattachées dont la valeur n'est attribuée à aucune personne, triés."""
    rows = conn.execute(
        text(f"""
            SELECT DISTINCT sa.person_id, aik.person_identifiers->>'{_IDHAL}' AS value
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.person_id IS NOT NULL
              AND aik.person_identifiers ? '{_IDHAL}'
              AND NOT {identifier_neutralized(f"'{_IDHAL}'")}
              AND NOT EXISTS (
                  SELECT 1 FROM person_identifiers pi
                  WHERE pi.id_type = '{_IDHAL}'
                    AND pi.id_value = aik.person_identifiers->>'{_IDHAL}'
              )
            ORDER BY 1, 2
        """)
    ).all()
    return [(r.person_id, r.value) for r in rows]


def _count_idhal(conn: Connection) -> int:
    return conn.execute(
        text(f"SELECT COUNT(*) FROM person_identifiers WHERE id_type = '{_IDHAL}'")
    ).scalar_one()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        pairs = _unattributed(conn)
        persons = {person_id for person_id, _ in pairs}
        values = {value for _, value in pairs}
        log.info(
            "%d couples (personne, idHAL) à attribuer : %d personnes, %d valeurs dont %d portées par plusieurs personnes",
            len(pairs),
            len(persons),
            len(values),
            len(pairs) - len(values),
        )
        if not apply:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        before = _count_idhal(conn)
        repo = person_repository(conn)
        for person_id, value in pairs:
            add_identifiers_from_authorships(person_id, [{_IDHAL: value}], repo=repo)
        conn.commit()
        log.info("✓ %d idHAL attribués", _count_idhal(conn) - before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
