# STATUS: oneshot (2026-10-22)
"""Transfère les épinglages de contributions sources hors groupe vers leurs doubles groupés.

Une contribution source hors groupe est un doublon d'auteur (`duplicate_of`) ou appartient à un enregistrement source écarté de l'alignement. Ses doubles sont l'original pour un doublon d'auteur, et sinon les contributions sources groupées de la même publication au même nom normalisé. Chaque double reçoit l'épinglage, puis l'épinglage de la contribution source hors groupe est supprimé. Un épinglage reste en place quand il n'a aucun double, ou quand un double est épinglé à une autre personne.

Usage :
    python -m interfaces.cli.oneshot.transfer_ungrouped_pins            # exécution
    python -m interfaces.cli.oneshot.transfer_ungrouped_pins --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("transfer_ungrouped_pins", os.path.dirname(__file__))

_PINS = text("""
    SELECT csc.source_contribution_id AS pinned, csc.person_id,
           CASE WHEN sc.duplicate_of IS NOT NULL THEN ARRAY[sc.duplicate_of]
                ELSE ARRAY(
                    SELECT o.id FROM source_contributions o
                    JOIN source_records osr ON osr.id = o.source_record_id
                    JOIN contributor_information oci ON oci.id = o.contributor_information_id
                    WHERE osr.publication_id = sr.publication_id
                      AND oci.author_name_normalized = ci.author_name_normalized
                      AND EXISTS (SELECT 1 FROM aligned_source_contributions gm
                                  WHERE gm.source_contribution_id = o.id)
                    ORDER BY o.id)
           END AS doubles
    FROM confirmed_source_contributions csc
    JOIN source_contributions sc ON sc.id = csc.source_contribution_id
    JOIN source_records sr ON sr.id = sc.source_record_id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE sr.publication_id IS NOT NULL AND NOT sc.collective
      AND NOT EXISTS (SELECT 1 FROM aligned_source_contributions gm
                      WHERE gm.source_contribution_id = sc.id)
    ORDER BY csc.source_contribution_id
""")

_PINNED_TO = text("""
    SELECT source_contribution_id, person_id FROM confirmed_source_contributions
    WHERE source_contribution_id = ANY(:ids)
""")

_PIN = text("""
    INSERT INTO confirmed_source_contributions (source_contribution_id, person_id)
    SELECT unnest(CAST(:ids AS integer[])), :person
    ON CONFLICT (source_contribution_id) DO NOTHING
""")

_UNPIN = text("DELETE FROM confirmed_source_contributions WHERE source_contribution_id = :id")


def transfer_pins(conn: Connection) -> Counter[str]:
    """Transfère les épinglages, dans la transaction du caller, et rend le décompte des issues."""
    outcomes: Counter[str] = Counter()
    for pin in conn.execute(_PINS).all():
        if not pin.doubles:
            log.info("%s : aucun double groupé, épinglage gardé", pin.pinned)
            outcomes["sans double"] += 1
            continue
        pinned_to = dict(conn.execute(_PINNED_TO, {"ids": list(pin.doubles)}).all())
        if any(person != pin.person_id for person in pinned_to.values()):
            log.warning(
                "%s : un double est épinglé à une autre personne (%s)", pin.pinned, pinned_to
            )
            outcomes["double épinglé à une autre personne"] += 1
            continue
        conn.execute(_PIN, {"ids": list(pin.doubles), "person": pin.person_id})
        conn.execute(_UNPIN, {"id": pin.pinned})
        log.info("%s → %s (personne %s)", pin.pinned, list(pin.doubles), pin.person_id)
        outcomes["transférés"] += 1
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        outcomes = transfer_pins(conn)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    for label, n in outcomes.items():
        log.info("%s : %d", label, n)
    log.info("DRY-RUN — aucune écriture" if args.dry_run else "✓ épinglages transférés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
