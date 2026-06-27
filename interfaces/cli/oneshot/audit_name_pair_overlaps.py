"""Audit (lecture seule) — recouvrements de réseau des paires candidates par nom.

Le rapprochement par nom (file « Doublons par nom » du hub) part de paires de personnes aux noms
compatibles, qu'il faut ensuite classer homonyme légitime vs doublon. L'hypothèse de travail : un
homonyme a des **réseaux disjoints** (co-auteurs, labos, revues, sujets sans recouvrement), un
doublon les a **communs**. Avant de figer une présentation ou un score, cet audit mesure ces
recouvrements sur les paires candidates réelles, pour voir lesquels discriminent et où passe la
frontière.

Les paires candidates réutilisent la génération existante (`PERSON_DUP_QUERIES`, 4 requêtes larges)
resserrée par `names_compatible` (comparaison par tokens) — la source de paires de la file
« Doublons par nom » du hub `admin/persons`. Pour chaque paire, on compte l'intersection de cinq dimensions :
co-auteurs, laboratoires, revues, sujets, et publications directement co-signées.

Rien n'est écrit.
"""

import sys
from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, bindparam, text

from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.api.persons.admin import PERSON_DUP_QUERIES

# Une dimension = (étiquette, SQL renvoyant (person_id, valeur) pour les personnes ciblées).
# Toutes au grain `authorships` (paires consolidées, rôle quelconque).
_DIMENSIONS: dict[str, str] = {
    "coauteurs": """
        SELECT a1.person_id AS person, a2.person_id AS val
        FROM authorships a1
        JOIN authorships a2 ON a2.publication_id = a1.publication_id AND a2.person_id <> a1.person_id
        WHERE a1.person_id = ANY(:ids) AND a2.person_id IS NOT NULL
    """,
    "labos": """
        SELECT a.person_id AS person, aus.structure_id AS val
        FROM authorships a
        JOIN authorship_structures aus ON aus.authorship_id = a.id
        JOIN structures s ON s.id = aus.structure_id AND s.structure_type = 'labo'
        WHERE a.person_id = ANY(:ids)
    """,
    "revues": """
        SELECT a.person_id AS person, p.journal_id AS val
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        WHERE a.person_id = ANY(:ids) AND p.journal_id IS NOT NULL
    """,
    "sujets": """
        SELECT a.person_id AS person, ps.subject_id AS val
        FROM authorships a
        JOIN publication_subjects ps ON ps.publication_id = a.publication_id
        WHERE a.person_id = ANY(:ids)
    """,
    "publis_communes": """
        SELECT a.person_id AS person, a.publication_id AS val
        FROM authorships a
        WHERE a.person_id = ANY(:ids)
    """,
}


def _load_sets(conn: Connection, sql: str, ids: list[int]) -> dict[int, set[int]]:
    """{person_id: {valeurs}} pour une dimension donnée."""
    out: dict[int, set[int]] = defaultdict(set)
    for r in conn.execute(text(sql).bindparams(bindparam("ids")), {"ids": ids}):
        out[r.person].add(r.val)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    conn: Connection = get_sync_engine().connect()
    try:
        # Paires candidates : union des 4 requêtes, dédupliquées, resserrées par tokens.
        seen: set[tuple[int, int]] = set()
        pairs: list[tuple[int, int, str, str]] = []
        for sql in PERSON_DUP_QUERIES:
            for r in conn.execute(text(sql)):
                key = (r.id_a, r.id_b)
                if key in seen:
                    continue
                seen.add(key)
                if names_compatible(r.ln1 or "", r.fn1 or "", r.ln2 or "", r.fn2 or ""):
                    a = f"{r.ln1} {r.fn1}".strip()
                    b = f"{r.ln2} {r.fn2}".strip()
                    pairs.append((r.id_a, r.id_b, a, b))
        print(f"  {len(pairs)} paires candidates (noms compatibles)\n")
        if not pairs:
            return

        ids = sorted({pid for p in pairs for pid in (p[0], p[1])})
        sets = {dim: _load_sets(conn, sql, ids) for dim, sql in _DIMENSIONS.items()}

        # Recouvrement par paire et par dimension.
        dims = list(_DIMENSIONS)
        overlap_hist: dict[str, dict[int, int]] = {d: defaultdict(int) for d in dims}
        any_network = 0  # ≥1 co-auteur OU ≥1 labo commun
        no_overlap = 0  # aucune dimension en commun
        samples_dup: list[Any] = []
        samples_homonym: list[Any] = []

        for id_a, id_b, a, b in pairs:
            counts = {}
            for d in dims:
                inter = len(sets[d].get(id_a, set()) & sets[d].get(id_b, set()))
                counts[d] = inter
                # Histogramme borné (0,1,2,3,4,5+).
                overlap_hist[d][min(inter, 5)] += 1
            has_network = counts["coauteurs"] > 0 or counts["labos"] > 0
            total_overlap = sum(counts.values())
            if has_network:
                any_network += 1
                if len(samples_dup) < 15:
                    samples_dup.append((a, b, counts))
            if total_overlap == 0:
                no_overlap += 1
                if len(samples_homonym) < 15:
                    samples_homonym.append((a, b))

        print("=== recouvrement par dimension (nb de paires ayant N éléments en commun) ===")
        print(
            f"  {'dimension':>16s} | {'0':>6s} {'1':>6s} {'2':>6s} {'3':>6s} {'4':>6s} {'5+':>6s}"
        )
        for d in dims:
            h = overlap_hist[d]
            print(f"  {d:>16s} | {h[0]:>6d} {h[1]:>6d} {h[2]:>6d} {h[3]:>6d} {h[4]:>6d} {h[5]:>6d}")

        n = len(pairs)
        print(
            f"\n  Paires avec réseau commun (≥1 co-auteur ou labo) : {any_network} ({100 * any_network / n:.1f}%)"
        )
        print(
            f"  Paires sans aucun recouvrement (5 dim. = 0)      : {no_overlap} ({100 * no_overlap / n:.1f}%)"
        )

        print("\n--- échantillon RÉSEAU COMMUN (doublon probable) : A | B | recouvrements ---")
        for a, b, counts in samples_dup:
            detail = " ".join(f"{d}={counts[d]}" for d in dims if counts[d])
            print(f"  {a!r} | {b!r} | {detail}")

        print("\n--- échantillon SANS RECOUVREMENT (homonyme probable) : A | B ---")
        for a, b in samples_homonym:
            print(f"  {a!r} | {b!r}")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
