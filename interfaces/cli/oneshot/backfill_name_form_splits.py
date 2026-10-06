# STATUS: oneshot (2026-10-06)
"""Découpe en nom et prénom les formes de nom des personnes qui portent un verdict (confirmée, rejetée).

Une forme `name_form` est une chaîne unique (« dupont marie »). Ce script renseigne `last_name_normalized` et `first_name_normalized` quand le découpage est certain, essais dans l'ordre :

- la chaîne est une forme de la personne elle-même (`person_name_form_splits`) ;
- une seule identité de signature porte cette chaîne dans l'ordre « prénom nom » (`author_identifying_keys.author_name_normalized`) ;
- une seule identité la porte dans l'ordre « nom prénom », celui des signatures au format « Nom, Prénom ».

Quand plusieurs identités la portent avec des découpages différents, `_choose` en retient un. Une forme qu'aucune identité ne porte, dans aucun ordre, est supprimée. Le script rapporte les formes restantes. Rejouable : il traite les seules formes encore sans découpage.

Usage :
    python -m interfaces.cli.oneshot.backfill_name_form_splits            # exécution
    python -m interfaces.cli.oneshot.backfill_name_form_splits --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, bindparam, text

from domain.normalize import clean_raw_author_name, normalize_name
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

# Clé de rapprochement d'une identité avec une forme, par ordre essayé.
_ORDERS = {
    "identité de signature, prénom nom": "author_name_normalized",
    "identité de signature, nom prénom": (
        "CASE WHEN first_name_normalized IS NOT NULL"
        " THEN last_name_normalized || ' ' || first_name_normalized END"
    ),
}

_DELETE_SQL = text("""
    DELETE FROM person_name_forms f
    USING jsonb_to_recordset(:payload) AS t(name_form text, person_id integer)
    WHERE f.name_form = t.name_form AND f.person_id = t.person_id
""").bindparams(bindparam("payload", type_=Jsonb))

_UPDATE_SQL = text("""
    UPDATE person_name_forms f
    SET last_name_normalized = t.last_name, first_name_normalized = t.first_name
    FROM jsonb_to_recordset(:payload) AS t(
        name_form text, person_id integer, last_name text, first_name text)
    WHERE f.name_form = t.name_form AND f.person_id = t.person_id
""").bindparams(bindparam("payload", type_=Jsonb))


_Split = tuple[str, str | None]


def _identity_splits(conn: Connection, key: str, forms: list[str]) -> dict[str, Counter[_Split]]:
    """Découpages (nom, prénom) des identités dont la clé `key` (expression SQL) vaut l'une des `forms`, avec leur nombre de signatures."""
    rows = conn.execute(
        text(f"""
            SELECT {key} AS name_form, aik.last_name_normalized, aik.first_name_normalized,
                   count(*) AS signatures
            FROM author_identifying_keys aik
            JOIN source_authorships sa ON sa.identity_id = aik.id
            WHERE {key} = ANY(:forms)
            GROUP BY 1, 2, 3
        """),
        {"forms": forms},
    )
    splits: dict[str, Counter[_Split]] = {}
    for r in rows:
        splits.setdefault(r.name_form, Counter())[
            (r.last_name_normalized, r.first_name_normalized)
        ] += r.signatures
    return splits


def _choose(splits: Counter[_Split], person_last_name: str) -> tuple[str, _Split] | None:
    """Découpage retenu parmi plusieurs, avec la règle qui l'a choisi ; `None` si aucune ne tranche.

    Règles dans l'ordre : nom égal à celui de la fiche de la personne, nom sans initiale, découpage porté par le plus de signatures.
    """
    same_last = [s for s in splits if s[0] == person_last_name]
    if len(same_last) == 1:
        return "nom de la fiche", same_last[0]
    without_initials = [s for s in splits if not any(len(w) == 1 for w in s[0].split())]
    if len(without_initials) == 1:
        return "nom sans initiale", without_initials[0]
    ranked = sorted(without_initials or splits, key=lambda s: -splits[s])
    if len(ranked) == 1 or splits[ranked[0]] > splits[ranked[1]]:
        return "plus de signatures", ranked[0]
    return None


def backfill(conn: Connection, *, apply: bool) -> Counter[str]:
    """Renseigne le découpage des formes à verdict quand il est certain, supprime celles qu'aucune identité ne porte. Retourne les comptes par issue et par verdict."""
    rows = conn.execute(_FORMS_SQL).all()
    forms = sorted({r.name_form for r in rows})
    candidates_by_order = {
        issue: _identity_splits(conn, key, forms) for issue, key in _ORDERS.items()
    }
    stats: Counter[str] = Counter()
    updates, deletes = [], []
    for row in rows:
        key = {"name_form": row.name_form, "person_id": row.person_id}
        split = person_name_form_splits(row.last_name, row.first_name or "").get(row.name_form)
        issue = "fiche de la personne"
        if split is None:
            found = [
                (o, c[row.name_form]) for o, c in candidates_by_order.items() if row.name_form in c
            ]
            if not found:
                stats[f"{row.status} : aucune identité, supprimée"] += 1
                deletes.append(key)
                continue
            issue, splits = found[0]
            if len(splits) == 1:
                (split,) = splits
            else:
                chosen = _choose(splits, normalize_name(clean_raw_author_name(row.last_name)))
                if chosen is None:
                    stats[f"{row.status} : plusieurs découpages, aucune règle ne tranche"] += 1
                    continue
                rule, split = chosen
                issue = f"plusieurs découpages, {rule}"
        stats[f"{row.status} : {issue}"] += 1
        updates.append({**key, "last_name": split[0], "first_name": split[1]})
    if apply and updates:
        conn.execute(_UPDATE_SQL, {"payload": updates})
    if apply and deletes:
        conn.execute(_DELETE_SQL, {"payload": deletes})
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
