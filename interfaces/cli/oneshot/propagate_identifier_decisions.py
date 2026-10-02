# STATUS: oneshot (2026-10-02)
"""Étend les décisions déjà prises sur les identifiants aux identifiants `pending` de leurs comptes HAL.

Chaque identifiant confirmé, authentifié ou rejeté propose son statut aux identifiants `pending` de la même personne que portent ses comptes HAL (`hal_account_peers`) ; un identifiant authentifié propose `confirmed`. Un identifiant `pending` reçoit le statut proposé quand toutes les propositions concordent ; un identifiant qui reçoit à la fois une confirmation et un rejet reste `pending` et figure au rapport.

Usage :
    python -m interfaces.cli.oneshot.propagate_identifier_decisions            # exécution
    python -m interfaces.cli.oneshot.propagate_identifier_decisions --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("propagate_identifier_decisions", os.path.dirname(__file__))

# Statut que propose un identifiant tranché.
_PROPOSED = {
    AttributionStatus.CONFIRMED.value: AttributionStatus.CONFIRMED.value,
    AttributionStatus.AUTHENTICATED.value: AttributionStatus.CONFIRMED.value,
    AttributionStatus.REJECTED.value: AttributionStatus.REJECTED.value,
}


def _decided(conn: Connection) -> dict[int, str]:
    """`{id: statut proposé}` des identifiants tranchés."""
    return {
        r.id: _PROPOSED[r.status]
        for r in conn.execute(
            text(
                "SELECT id, status::text AS status FROM person_identifiers "
                "WHERE status::text = ANY(:statuses)"
            ),
            {"statuses": list(_PROPOSED)},
        )
    }


def _describe(conn: Connection, ident_ids: list[int]) -> dict[int, str]:
    return {
        r.id: f"personne {r.person_id} {r.id_type}={r.id_value}"
        for r in conn.execute(
            text(
                "SELECT id, person_id, id_type, id_value FROM person_identifiers WHERE id = ANY(:ids)"
            ),
            {"ids": ident_ids},
        )
    }


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
        repo = person_repository(conn)
        decided = _decided(conn)
        proposals: dict[int, set[str]] = defaultdict(set)
        for src_id, peer_ids in repo.hal_account_peers(list(decided)).items():
            for peer_id in peer_ids:
                proposals[peer_id].add(decided[src_id])

        agreed = {
            peer: statuses.pop() for peer, statuses in proposals.items() if len(statuses) == 1
        }
        conflicting = sorted(peer for peer, statuses in proposals.items() if len(statuses) > 1)
        log.info(
            "%d identifiants tranchés ; %d identifiants pending reçoivent un statut : %s",
            len(decided),
            len(agreed),
            ", ".join(f"{n} {status}" for status, n in sorted(Counter(agreed.values()).items())),
        )
        if conflicting:
            log.warning(
                "%d identifiants restent pending, confirmés et rejetés à la fois par leur groupe :",
                len(conflicting),
            )
            for description in _describe(conn, conflicting).values():
                log.warning("  %s", description)

        if not apply:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        for ident_id, status in agreed.items():
            repo.update_identifier_status(ident_id, status)
        conn.commit()
        log.info("✓ %d statuts appliqués", len(agreed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
