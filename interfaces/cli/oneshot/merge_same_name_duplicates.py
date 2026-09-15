# STATUS: oneshot (2026-09-15)
"""Fusionne les personnes de même nom et même prénom, quand rien ne les distingue.

Un groupe de personnes aux nom et prénom plein normalisés identiques fusionne dans une seule personne quand au plus une personne du groupe a une fiche RH, qu'aucun identifiant à valeur unique (ORCID, IdRef, idHAL) n'y prend deux valeurs, et qu'aucune paire du groupe n'est marquée distincte. La personne absorbante est celle qui a une fiche RH, sinon la plus ancienne. Les autres groupes restent à trancher dans la file « Doublons par nom » de `admin/persons`.

Usage :
    python -m interfaces.cli.oneshot.merge_same_name_duplicates            # exécution
    python -m interfaces.cli.oneshot.merge_same_name_duplicates --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from itertools import combinations

from sqlalchemy import Connection, Row, text

from application.services.persons.core import merge_person
from domain.errors import ConflictError
from domain.normalize import normalize_name
from domain.persons.name_matching import first_name_initials
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("merge_same_name_duplicates", os.path.dirname(__file__))

# Types d'identifiant dont une personne porte au plus une valeur.
_SINGLE_VALUED = ("orcid", "idref", "idhal")


def _groups(conn: Connection) -> list[list[Row[tuple[object, ...]]]]:
    """Groupes d'au moins deux personnes non rejetées aux nom et prénom plein normalisés identiques, chacun trié par id."""
    rows = conn.execute(
        text("""
            SELECT p.id, p.last_name, COALESCE(p.first_name, '') AS first_name,
                   EXISTS (SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh,
                   (SELECT COUNT(*) FROM source_authorships sa
                    WHERE sa.person_id = p.id) AS signatures
            FROM persons p
            WHERE NOT p.rejected
            ORDER BY p.id
        """)
    ).all()
    groups: dict[tuple[str, str], list[Row[tuple[object, ...]]]] = defaultdict(list)
    for r in rows:
        if normalize_name(r.first_name) and first_name_initials(r.first_name) is None:
            groups[(normalize_name(r.last_name), normalize_name(r.first_name))].append(r)
    return [group for group in groups.values() if len(group) > 1]


def _identifiers(conn: Connection) -> dict[tuple[int, str], set[str]]:
    """`{(person_id, id_type): valeurs}` des identifiants à valeur unique non rejetés."""
    values: dict[tuple[int, str], set[str]] = defaultdict(set)
    for r in conn.execute(
        text("""
            SELECT person_id, id_type::text AS id_type, id_value
            FROM person_identifiers
            WHERE status <> 'rejected' AND id_type::text = ANY(:types)
        """),
        {"types": list(_SINGLE_VALUED)},
    ):
        values[(r.person_id, r.id_type)].add(r.id_value)
    return values


def _blocker(
    group: list[Row[tuple[object, ...]]],
    identifiers: dict[tuple[int, str], set[str]],
    distinct: set[frozenset[int]],
) -> str | None:
    """Ce qui distingue les personnes du groupe, `None` si rien ne les distingue."""
    if sum(r.has_rh for r in group) > 1:
        return "plusieurs fiches RH"
    for id_type in _SINGLE_VALUED:
        if len({v for r in group for v in identifiers.get((r.id, id_type), ())}) > 1:
            return f"{id_type} en conflit"
    if any(frozenset((a.id, b.id)) in distinct for a, b in combinations(group, 2)):
        return "paire marquée distincte"
    return None


def _describe(r: Row[tuple[object, ...]]) -> str:
    return f"{r.id}{' RH' if r.has_rh else ''} ({r.signatures} sig.)"


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
        groups = _groups(conn)
        identifiers = _identifiers(conn)
        distinct = {
            frozenset((r.person_id_a, r.person_id_b))
            for r in conn.execute(text("SELECT person_id_a, person_id_b FROM distinct_persons"))
        }
        repo = person_repository(conn)
        merged = kept = 0
        for group in groups:
            name = f"{group[0].last_name} {group[0].first_name}"
            blocker = _blocker(group, identifiers, distinct)
            if blocker is not None:
                kept += 1
                log.info("%s : écarté (%s) — %s", name, blocker, ", ".join(map(_describe, group)))
                continue
            target = next((r for r in group if r.has_rh), group[0])
            sources = [r for r in group if r.id != target.id]
            log.info("%s : %s ← %s", name, _describe(target), ", ".join(map(_describe, sources)))
            if not apply:
                continue
            for source in sources:
                try:
                    merge_person(target.id, source.id, repo=repo)
                except ConflictError as exc:
                    log.warning("%d → %d écarté : %s", source.id, target.id, exc)
                    continue
                merged += 1
        log.info("groupes : %d, écartés : %d", len(groups), kept)
        if apply:
            conn.commit()
            log.info("✓ %d fusions appliquées", merged)
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
