# STATUS: oneshot (2026-10-06)
"""Découpe en nom et prénom les formes de nom des personnes qui portent un verdict (confirmée, rejetée).

Une forme `name_form` est une chaîne unique (« dupont marie »). Ce script renseigne `last_name_normalized` et `first_name_normalized` quand le découpage est certain :

- la chaîne est une forme de la personne elle-même (`person_name_form_splits`) ;
- sinon, une seule identité de signature découpée porte cette chaîne (`author_identifying_keys.author_name_normalized`).

Il rapporte les formes restantes : aucun découpage, ou plusieurs. Rejouable : il traite les seules formes encore sans découpage.

Usage :
    python -m interfaces.cli.oneshot.backfill_name_form_splits            # exécution
    python -m interfaces.cli.oneshot.backfill_name_form_splits --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, bindparam, text

from domain.persons.name_forms import person_name_form_splits
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_name_form_splits", os.path.dirname(__file__))

_FORMS_SQL = text("""
    SELECT f.name_form, f.person_id, f.status::text AS status, p.last_name, p.first_name
    FROM person_name_forms f
    JOIN persons p ON p.id = f.person_id
    WHERE f.status <> 'pending' AND f.last_name_normalized IS NULL
""")

_IDENTITY_SPLITS_SQL = text("""
    SELECT author_name_normalized AS name_form,
           array_agg(DISTINCT last_name_normalized) AS lasts,
           array_agg(DISTINCT coalesce(first_name_normalized, '')) AS firsts,
           count(DISTINCT (last_name_normalized, first_name_normalized)) AS n
    FROM author_identifying_keys
    WHERE author_name_normalized = ANY(:forms)
    GROUP BY author_name_normalized
""")

_UPDATE_SQL = text("""
    UPDATE person_name_forms f
    SET last_name_normalized = t.last_name, first_name_normalized = t.first_name
    FROM jsonb_to_recordset(:payload) AS t(
        name_form text, person_id integer, last_name text, first_name text)
    WHERE f.name_form = t.name_form AND f.person_id = t.person_id
""").bindparams(bindparam("payload", type_=Jsonb))


def backfill(conn: Connection, *, apply: bool) -> Counter[str]:
    """Renseigne le découpage des formes à verdict quand il est certain. Retourne les comptes par issue et par verdict."""
    rows = conn.execute(_FORMS_SQL).all()
    identity_splits = {
        r.name_form: r
        for r in conn.execute(_IDENTITY_SPLITS_SQL, {"forms": sorted({r.name_form for r in rows})})
    }
    stats: Counter[str] = Counter()
    payload = []
    for row in rows:
        split = person_name_form_splits(row.last_name, row.first_name or "").get(row.name_form)
        issue = "fiche de la personne"
        if split is None:
            candidates = identity_splits.get(row.name_form)
            if candidates is None:
                stats[f"{row.status} : aucun découpage"] += 1
                continue
            if candidates.n > 1:
                stats[f"{row.status} : plusieurs découpages"] += 1
                continue
            split = (candidates.lasts[0], candidates.firsts[0] or None)
            issue = "identité de signature"
        stats[f"{row.status} : {issue}"] += 1
        payload.append(
            {
                "name_form": row.name_form,
                "person_id": row.person_id,
                "last_name": split[0],
                "first_name": split[1],
            }
        )
    if apply and payload:
        conn.execute(_UPDATE_SQL, {"payload": payload})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    with get_sync_engine().connect() as conn:
        for issue, count in sorted(backfill(conn, apply=apply).items()):
            log.info("%s : %d", issue, count)
        if apply:
            conn.commit()
            log.info("✓ découpages enregistrés")
        else:
            log.info("DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
