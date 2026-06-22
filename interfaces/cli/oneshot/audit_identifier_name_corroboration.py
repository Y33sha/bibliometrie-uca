"""Audit (lecture seule) — corroboration par le nom au matching par identifiant.

Outille la décision du levier « rejeter un match identifiant dont le nom est
incompatible avec la personne ciblée » (chantier
`DATA_personnes-dedoublonnage-assiste`). Deux analyses indépendantes, lecture
seule, réutilisant les fonctions domaine pour coller au comportement réel.

`--rates` : sur tous les `source_authorships` portant un identifiant
(orcid/idref/hal_person_id non `_dubious`) qui résout vers une personne connue,
ventile compatible / abstention (signature trop pauvre) / incompatible (nom de
famille compatible mais prénom divergent, ou totalement incompatible).

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
import re
import sys
from collections import defaultdict

from sqlalchemy import text

from domain.normalize import normalize_name
from domain.persons.name_matching import (
    last_names_compatible,
    names_compatible,
    parse_raw_author_name,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.api.person_duplicates import _tokens_match

ORCID_MATCH_SOURCES = frozenset({"crossref", "openalex", "hal"})
ID_TYPES = ("orcid", "idref", "hal_person_id")


def load_target_map(conn, id_type):
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


def _sig(raw_name):
    """Signature normalisée (last_norm, first_norm) comme dans la cascade."""
    last, first = parse_raw_author_name(raw_name)
    return normalize_name(last), normalize_name(first)


def _clean(s):
    """Normalisation de comparaison de noms : comme `normalize_name` mais SANS les
    chiffres. Les années de naissance collées aux signatures de type SUDOC
    (« Chiari, Sophie 1977- ») parasitent sinon les tokens et faussent la
    comparaison. Exception assumée à la normalisation habituelle (qui conserve
    [a-z0-9]), d'où une fonction ad hoc propre à la comparaison de noms."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", " ", normalize_name(s or ""))).strip()


def name_compatible_strict(raw_name, target_ln, target_fn):
    """Comparaison positionnelle de la cascade (`names_compatible`), entrées nettoyées (sans chiffres)."""
    last, first = parse_raw_author_name(raw_name)
    return names_compatible(_clean(last), _clean(first), _clean(target_ln), _clean(target_fn))


def name_compatible_tokens(raw_name, target_ln, target_fn):
    """Comparaison par ensemble de tokens (`_tokens_match`), entrées nettoyées (sans chiffres).

    Indépendante de l'ordre et tolérante aux initiales : réconcilie « P.M. Llorca »
    avec « Pierre-Michel Llorca », les noms multi-mots et les noms composés réordonnés."""
    sig = set(_clean(raw_name).split())
    person = set(_clean(f"{target_ln} {target_fn}").split())
    return _tokens_match(sig, person)


def classify(sig_ln, sig_fn, target_ln, target_fn):
    """compatible / abstain / incompat_strong / incompat_firstname."""
    if names_compatible(sig_ln, sig_fn, target_ln, target_fn):
        return "compatible"
    if not sig_fn or not target_fn:
        return "abstain"
    if last_names_compatible(sig_ln, target_ln) or last_names_compatible(sig_ln, target_fn):
        return "incompat_firstname"
    return "incompat_strong"


def audit_rates(conn, maps):
    """Ventilation compatible / abstention / incompatible par type d'identifiant."""
    stats = {t: defaultdict(int) for t in ID_TYPES}
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
        sig_ln, sig_fn = _sig(row.name)
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
            stats[t][classify(sig_ln, sig_fn, target[1], target[2])] += 1

    print(f"\n[--rates] source_authorships portant un identifiant scannées : {n}\n")
    for t in ID_TYPES:
        s = stats[t]
        resolved = s["resolved"]
        print(f"=== {t} ===")
        print(f"  id inconnu (no-op)        : {s['unknown_id']}")
        print(f"  résolus vers une personne : {resolved}")
        if resolved:
            for k in ("compatible", "abstain", "incompat_firstname", "incompat_strong"):
                print(f"    {k:20s} : {s[k]:7d}  ({100 * s[k] / resolved:5.1f}%)")
        print()


def audit_double_occurrence(conn, maps, name_compat):
    """Intrus identifiant + occurrence légitime de la même personne sur la même publi.

    `name_compat(raw_name, target_ln, target_fn) -> bool` : comparateur de noms
    (strict positionnel ou par tokens) injecté pour mesurer l'impact du choix.

    Un seul passage : on accumule les présences légitimes
    `(source_publication_id, person_id)` (authorship au nom compatible avec sa
    personne) et les intrus (authorship au nom incompatible avec sa personne, mais
    portant un identifiant qui résout vers cette même personne). On croise ensuite.
    """
    legit_example = {}  # (spid, person_id) -> nom compatible (une occurrence)
    intruders = []  # (spid, person_id, id_type, id_value, name, source)

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
        if name_compat(row.name, row.pln, row.pfn):
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
    by_type = defaultdict(int)
    by_source = defaultdict(int)
    by_type_source = defaultdict(int)
    for spid, pid, t, val, name, source in confirmed:
        by_type[t] += 1
        by_source[source] += 1
        by_type_source[(t, source)] += 1
    distinct_pairs = {(i[0], i[1]) for i in confirmed}
    distinct_persons = {i[1] for i in confirmed}

    print(f"\n[--double-occurrence] source_authorships rattachées scannées : {n}\n")
    print(f"  intrus identifiant (nom incompatible avec la personne ciblée) : {len(intruders)}")
    print(f"  dont CONFIRMÉS par une occurrence légitime sur la même publi  : {len(confirmed)}")
    print(f"    par type : " + ", ".join(f"{t}={by_type[t]}" for t in ID_TYPES))
    print(
        f"    par source : "
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


def audit_comparators(conn):
    """Désaccords entre `names_compatible` (positionnel) et la comparaison par tokens.

    Population bornée et réelle : chaque `source_authorship` rattachée, comparée à
    sa personne assignée. La quasi-totalité des rattachements étant corrects, les
    désaccords isolent où les deux comparateurs divergent sur de vraies paires :
    `tokens_only` = tokens accepte là où le positionnel rejette (gain de rappel) ;
    `strict_only` = le positionnel accepte là où tokens rejette (perte de rappel
    possible de tokens). À juger à l'œil."""
    counts = defaultdict(int)
    strict_only, tokens_only = [], []
    result = conn.execution_options(stream_results=True).execute(
        text("""
            SELECT sa.raw_author_name AS name,
                   p.last_name_normalized AS pln, p.first_name_normalized AS pfn
            FROM source_authorships sa
            JOIN persons p ON p.id = sa.person_id
            WHERE sa.person_id IS NOT NULL AND sa.raw_author_name IS NOT NULL
        """)
    )
    n = 0
    for row in result:
        n += 1
        s = name_compatible_strict(row.name, row.pln, row.pfn)
        k = name_compatible_tokens(row.name, row.pln, row.pfn)
        if s and k:
            counts["agree_compatible"] += 1
        elif not s and not k:
            counts["agree_incompatible"] += 1
        elif s and not k:
            counts["strict_only"] += 1
            if len(strict_only) < 40:
                strict_only.append((row.name, f"{row.pfn} {row.pln}".strip()))
        else:
            counts["tokens_only"] += 1
            if len(tokens_only) < 40:
                tokens_only.append((row.name, f"{row.pfn} {row.pln}".strip()))

    total = n or 1
    print(f"\n[--compare] authorships rattachées comparées à leur personne : {n}\n")
    for k in ("agree_compatible", "agree_incompatible", "tokens_only", "strict_only"):
        print(f"  {k:20s} : {counts[k]:8d}  ({100 * counts[k] / total:5.2f}%)")
    print("\n--- tokens_only : tokens compatible, names_compatible NON (signature | personne) ---")
    for name, person in tokens_only:
        print(f"  {name!r:42s} | {person!r}")
    print("\n--- strict_only : names_compatible compatible, tokens NON (signature | personne) ---")
    for name, person in strict_only:
        print(f"  {name!r:42s} | {person!r}")
    print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rates", action="store_true", help="Ventilation compatible/incompatible")
    parser.add_argument(
        "--double-occurrence", action="store_true", help="Intrus identifiant + occurrence légitime"
    )
    parser.add_argument(
        "--compare", action="store_true", help="Désaccords names_compatible vs tokens"
    )
    parser.add_argument(
        "--name-match",
        choices=("strict", "tokens"),
        default="tokens",
        help="Comparateur de noms pour --double-occurrence (défaut : tokens)",
    )
    args = parser.parse_args()
    run_both = not (args.rates or args.double_occurrence or args.compare)
    name_compat = name_compatible_tokens if args.name_match == "tokens" else name_compatible_strict
    needs_maps = args.rates or args.double_occurrence or run_both

    conn = get_sync_engine().connect()
    try:
        if needs_maps:
            maps = {t: load_target_map(conn, t) for t in ID_TYPES}
            for t in ID_TYPES:
                print(f"  map {t}: {len(maps[t])} personnes")
        if args.rates or run_both:
            audit_rates(conn, maps)
        if args.double_occurrence or run_both:
            print(f"\n(comparateur de noms : {args.name_match})")
            audit_double_occurrence(conn, maps, name_compat)
        if args.compare or run_both:
            audit_comparators(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
