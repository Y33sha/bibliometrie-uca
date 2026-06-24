"""Audit (lecture seule) — corroboration par le nom au matching par identifiant.

Outille la décision du levier « rejeter un match identifiant dont le nom est
incompatible avec la personne ciblée » (chantier
`DATA_personnes-dedoublonnage-assiste`). Deux analyses indépendantes, lecture
seule, réutilisant `names_compatible` du domaine pour coller au comportement réel.

`--rates` : sur tous les `source_authorships` portant un identifiant
(orcid/idref/hal_person_id non `_dubious`) qui résout vers une personne connue,
ventile compatible / incompatible (nom de la signature vs nom de la personne ciblée).

`--double-occurrence` : répond à la question « quand un identifiant rattache une
authorship à une personne sous un nom incompatible, retrouve-t-on sur la **même**
`source_publication` une **autre** authorship rattachée à cette même personne sous
un nom **compatible** ? ». Cette double occurrence (une fois par identifiant, une
fois par nom) est un signal fort d'erreur d'attribution de l'identifiant : la
personne signe légitimement la publication (occurrence par nom), et l'identifiant
y a traîné une signature étrangère (occurrence par identifiant).

Sans argument : lance les deux. Rien n'est écrit.
"""

import argparse
import sys
from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, text

from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine

ORCID_MATCH_SOURCES = frozenset({"crossref", "openalex", "hal"})
ID_TYPES = ("orcid", "idref", "hal_person_id")


def load_target_map(conn: Connection, id_type: str) -> dict[str, tuple[int, str, str]]:
    """{id_value: (person_id, last_name_normalized, first_name_normalized)} pour
    les identifiants connus non rejetés (mêmes maps que la cascade de matching)."""
    rows = conn.execute(
        text("""
            SELECT pi.id_value, pi.person_id,
                   p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = :t AND pi.status <> 'rejected'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.ln or "", r.fn or "") for r in rows}


def audit_rates(conn: Connection, maps: dict[str, dict[str, tuple[int, str, str]]]) -> None:
    """Ventilation compatible / incompatible par type d'identifiant.

    `names_compatible` comparant par tokens (ordre indifférent), on passe la
    signature brute entière en premier argument et une chaîne vide en second."""
    stats: dict[str, dict[str, int]] = {t: defaultdict(int) for t in ID_TYPES}
    result = conn.execution_options(stream_results=True).execute(
        text("""
            SELECT sa.source::text AS source,
                   sa.raw_author_name AS name,
                   sa.person_identifiers->>'orcid' AS orcid,
                   sa.person_identifiers->>'idref' AS idref,
                   sa.person_identifiers->>'hal_person_id' AS hal_person_id
            FROM source_authorships sa
            WHERE sa.raw_author_name IS NOT NULL
              AND (sa.person_identifiers ? 'orcid'
                   OR sa.person_identifiers ? 'idref'
                   OR sa.person_identifiers ? 'hal_person_id')
        """)
    )
    n = 0
    for row in result:
        n += 1
        values = {"orcid": row.orcid, "idref": row.idref, "hal_person_id": row.hal_person_id}
        for t in ID_TYPES:
            val = values[t]
            if not val:
                continue
            if t == "orcid" and row.source not in ORCID_MATCH_SOURCES:
                continue
            target = maps[t].get(val)
            if target is None:
                stats[t]["unknown_id"] += 1
                continue
            stats[t]["resolved"] += 1
            compatible = names_compatible(row.name, "", target[1], target[2])
            stats[t]["compatible" if compatible else "incompatible"] += 1

    print(f"\n[--rates] source_authorships portant un identifiant scannées : {n}\n")
    for t in ID_TYPES:
        s = stats[t]
        resolved = s["resolved"]
        print(f"=== {t} ===")
        print(f"  id inconnu (no-op)        : {s['unknown_id']}")
        print(f"  résolus vers une personne : {resolved}")
        if resolved:
            for k in ("compatible", "incompatible"):
                print(f"    {k:14s} : {s[k]:7d}  ({100 * s[k] / resolved:5.1f}%)")
        print()


def audit_double_occurrence(
    conn: Connection, maps: dict[str, dict[str, tuple[int, str, str]]]
) -> None:
    """Intrus identifiant + occurrence légitime de la même personne sur la même publi.

    Un seul passage : on accumule les présences légitimes
    `(source_publication_id, person_id)` (authorship au nom compatible avec sa
    personne) et les intrus (authorship au nom incompatible avec sa personne, mais
    portant un identifiant qui résout vers cette même personne). On croise ensuite.
    """
    legit_example: dict[
        tuple[Any, Any], str
    ] = {}  # (spid, person_id) -> nom compatible (une occurrence)
    intruders: list[
        tuple[Any, Any, str, str, str, str]
    ] = []  # (spid, person_id, id_type, id_value, name, source)

    result = conn.execution_options(stream_results=True).execute(
        text("""
            SELECT sa.source_publication_id AS spid,
                   sa.person_id,
                   sa.source::text AS source,
                   sa.raw_author_name AS name,
                   sa.person_identifiers->>'orcid' AS orcid,
                   sa.person_identifiers->>'idref' AS idref,
                   sa.person_identifiers->>'hal_person_id' AS hal_person_id,
                   p.last_name_normalized AS pln, p.first_name_normalized AS pfn
            FROM source_authorships sa
            JOIN persons p ON p.id = sa.person_id
            WHERE sa.person_id IS NOT NULL
              AND sa.raw_author_name IS NOT NULL
        """)
    )
    n = 0
    for row in result:
        n += 1
        key = (row.spid, row.person_id)
        if names_compatible(row.name, "", row.pln, row.pfn):
            legit_example.setdefault(key, row.name)
            continue
        # Nom incompatible avec la personne rattachée : l'identifiant est-il la
        # cause du rattachement (il résout vers cette même personne) ?
        values = {"orcid": row.orcid, "idref": row.idref, "hal_person_id": row.hal_person_id}
        for t in ID_TYPES:
            val = values[t]
            if not val:
                continue
            if t == "orcid" and row.source not in ORCID_MATCH_SOURCES:
                continue
            target = maps[t].get(val)
            if target is not None and target[0] == row.person_id:
                intruders.append((row.spid, row.person_id, t, val, row.name, row.source))
                break

    confirmed = [i for i in intruders if (i[0], i[1]) in legit_example]
    by_type: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    by_type_source: dict[tuple[str, str], int] = defaultdict(int)
    for _spid, _pid, t, _val, _name, source in confirmed:
        by_type[t] += 1
        by_source[source] += 1
        by_type_source[(t, source)] += 1
    distinct_pairs = {(i[0], i[1]) for i in confirmed}
    distinct_persons = {i[1] for i in confirmed}

    print(f"\n[--double-occurrence] source_authorships rattachées scannées : {n}\n")
    print(f"  intrus identifiant (nom incompatible avec la personne ciblée) : {len(intruders)}")
    print(f"  dont CONFIRMÉS par une occurrence légitime sur la même publi  : {len(confirmed)}")
    print("    par type : " + ", ".join(f"{t}={by_type[t]}" for t in ID_TYPES))
    print(
        "    par source : "
        + ", ".join(f"{s}={c}" for s, c in sorted(by_source.items(), key=lambda x: -x[1]))
    )
    print("    par (type, source) :")
    for (t, s), c in sorted(by_type_source.items(), key=lambda x: -x[1]):
        print(f"      {t:14s} {s:10s} : {c}")
    print(f"    couples (source_publication, personne) distincts : {len(distinct_pairs)}")
    print(f"    personnes distinctes concernées                  : {len(distinct_persons)}")

    print("\n  échantillon (intrus par identifiant | occurrence légitime par nom | id | source) :")
    for spid, pid, t, val, name, source in confirmed[:30]:
        print(f"    {name!r:38s} | {legit_example[(spid, pid)]!r:32s} | {t}:{val} | {source}")
    print()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rates", action="store_true", help="Ventilation compatible/incompatible")
    parser.add_argument(
        "--double-occurrence", action="store_true", help="Intrus identifiant + occurrence légitime"
    )
    args = parser.parse_args()
    run_both = not (args.rates or args.double_occurrence)

    conn = get_sync_engine().connect()
    try:
        maps = {t: load_target_map(conn, t) for t in ID_TYPES}
        for t in ID_TYPES:
            print(f"  map {t}: {len(maps[t])} personnes")
        if args.rates or run_both:
            audit_rates(conn, maps)
        if args.double_occurrence or run_both:
            audit_double_occurrence(conn, maps)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
