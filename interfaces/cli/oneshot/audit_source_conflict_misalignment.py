"""Audit (lecture seule) — le détecteur « conflit de sources » face au désalignement des positions.

Le détecteur de doublons par conflit de sources joint deux `person_id` distincts sur une même
`(publication, author_position)` : la premisse est que la position d'auteur identifie le même slot
d'une source à l'autre. Sur les publications à beaucoup d'auteurs, les positions ne s'alignent plus
entre HAL / OpenAlex / WoS, et deux auteurs réellement différents partageant l'indice de position
produisent un **faux conflit**. Le contournement actuel exclut les publications de plus de 50 auteurs
(`MAX_AUTHORS_CONFLICT`).

Cet audit caractérise le caillou pour décider s'il mérite une fiche chantier ou s'il s'enterre :
il rejoue le détecteur **sans le cap**, et classe chaque conflit selon la **compatibilité des noms**
des deux personnes (par tokens, `names_compatible`) — discriminant attendu entre vrai doublon (noms
compatibles) et artefact de désalignement (noms incompatibles). La ventilation par tranche de nombre
d'auteurs montre où le signal bascule en bruit, donc si le cap de 50 est bien placé et si un garde de
compatibilité de nom suffirait à le remplacer.

Le « conflit » est mesuré au grain `(paire de personnes, publication)` : une paire en conflit sur
plusieurs positions d'une même publication compte une fois pour cette publication. Les paires déjà
marquées distinctes (`distinct_persons`) ne sont pas filtrées : elles font partie du bruit observé.

Rien n'est écrit.
"""

import sys
from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, text

from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine

# Conflits au grain (paire, publication) + noms normalisés des deux personnes + nombre d'auteurs de
# la publication (max sur les sources). Pas de cap : on veut justement voir au-delà de 50.
_CONFLICTS_SQL = text("""
    WITH pub_author_counts AS (
        SELECT publication_id, MAX(cnt) AS max_authors FROM (
            SELECT sd.publication_id, COUNT(*) AS cnt
            FROM source_publications sd
            JOIN source_authorships sa ON sa.source_publication_id = sd.id
            GROUP BY sd.publication_id, sa.source
        ) sub GROUP BY publication_id
    ),
    author_positions AS (
        SELECT DISTINCT sd.publication_id, sa.author_position, sa.person_id
        FROM source_publications sd
        JOIN source_authorships sa ON sa.source_publication_id = sd.id
        WHERE sa.person_id IS NOT NULL
    ),
    conflicts AS (
        SELECT DISTINCT
            LEAST(a1.person_id, a2.person_id) AS id_a,
            GREATEST(a1.person_id, a2.person_id) AS id_b,
            a1.publication_id
        FROM author_positions a1
        JOIN author_positions a2
          ON a1.publication_id = a2.publication_id
         AND a1.author_position = a2.author_position
         AND a1.person_id < a2.person_id
    )
    SELECT c.id_a, c.id_b, c.publication_id, pac.max_authors,
           pa.last_name_normalized AS a_ln, pa.first_name_normalized AS a_fn,
           pb.last_name_normalized AS b_ln, pb.first_name_normalized AS b_fn
    FROM conflicts c
    JOIN pub_author_counts pac ON pac.publication_id = c.publication_id
    JOIN persons pa ON pa.id = c.id_a
    JOIN persons pb ON pb.id = c.id_b
""")

# Bornes hautes des tranches de nombre d'auteurs (la dernière capte le reste).
_BUCKETS = [10, 50, 100, 250, 500, 1000]


def _bucket_label(max_authors: int) -> str:
    low = 1
    for high in _BUCKETS:
        if max_authors <= high:
            return f"{low}–{high}"
        low = high + 1
    return f">{_BUCKETS[-1]}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    conn: Connection = get_sync_engine().connect()
    try:
        rows = conn.execute(_CONFLICTS_SQL).all()
        print(f"  {len(rows)} conflits (paire, publication), toutes tailles confondues\n")

        # Compatibilité par paire (cache : une paire revient sur plusieurs publications).
        compat_cache: dict[tuple[int, int], bool] = {}

        def is_compatible(r: Any) -> bool:
            key = (r.id_a, r.id_b)
            if key not in compat_cache:
                compat_cache[key] = names_compatible(
                    r.a_ln or "", r.a_fn or "", r.b_ln or "", r.b_fn or ""
                )
            return compat_cache[key]

        # Tally par tranche : conflits (instances) + paires distinctes, scindés compatible/incompatible.
        order = [_bucket_label(b) for b in (1, *[b + 1 for b in _BUCKETS])]
        seen_order: list[str] = []
        inst_compat: dict[str, int] = defaultdict(int)
        inst_incompat: dict[str, int] = defaultdict(int)
        pairs_compat: dict[str, set[tuple[int, int]]] = defaultdict(set)
        pairs_incompat: dict[str, set[tuple[int, int]]] = defaultdict(set)

        for r in rows:
            bucket = _bucket_label(r.max_authors)
            if bucket not in seen_order:
                seen_order.append(bucket)
            if is_compatible(r):
                inst_compat[bucket] += 1
                pairs_compat[bucket].add((r.id_a, r.id_b))
            else:
                inst_incompat[bucket] += 1
                pairs_incompat[bucket].add((r.id_a, r.id_b))

        buckets = [b for b in order if b in seen_order] + [b for b in seen_order if b not in order]

        print(
            "=== ventilation par nombre d'auteurs (compat. = noms compatibles, vrai doublon probable) ==="
        )
        print(
            f"  {'tranche':>10s} | {'conflits':>9s} {'%compat':>8s} | "
            f"{'paires':>7s} {'compat':>7s} {'incompat':>9s}"
        )
        for b in buckets:
            inst = inst_compat[b] + inst_incompat[b]
            pc = len(pairs_compat[b])
            pi = len(pairs_incompat[b] - pairs_compat[b])
            pct = 100 * inst_compat[b] / inst if inst else 0.0
            print(f"  {b:>10s} | {inst:>9d} {pct:>7.1f}% | {pc + pi:>7d} {pc:>7d} {pi:>9d}")

        # Décision : combien de paires « vrai doublon probable » (noms compatibles) sont masquées
        # par le cap actuel (publication > 50 auteurs) ? = celles qui n'apparaissent QUE sur des
        # publications de plus de 50 auteurs (jamais ≤50).
        compat_le50: set[tuple[int, int]] = set()
        compat_gt50: set[tuple[int, int]] = set()
        for r in rows:
            if is_compatible(r):
                (compat_le50 if r.max_authors <= 50 else compat_gt50).add((r.id_a, r.id_b))
        only_hidden = compat_gt50 - compat_le50
        print(f"\n  Paires à noms compatibles (signal) au total : {len(compat_le50 | compat_gt50)}")
        print(f"  …visibles sous le cap actuel (≤50 auteurs)   : {len(compat_le50)}")
        print(f"  …masquées par le cap >50 (jamais ≤50)        : {len(only_hidden)}")

        # Échantillons pour l'œil.
        def sample(predicate: Any, label: str, limit: int = 12) -> None:
            print(f"\n--- échantillon {label} (pub | auteurs | A | B) ---")
            seen: set[tuple[int, int]] = set()
            n = 0
            for r in rows:
                if n >= limit:
                    break
                key = (r.id_a, r.id_b)
                if key in seen or not predicate(r):
                    continue
                seen.add(key)
                n += 1
                a = f"{r.a_ln} {r.a_fn}".strip()
                b = f"{r.b_ln} {r.b_fn}".strip()
                print(f"  {r.publication_id} | {r.max_authors:>4d} | {a!r} | {b!r}")

        sample(
            lambda r: is_compatible(r) and r.max_authors > 50,
            "COMPATIBLE au-delà de 50 (doublon masqué)",
        )
        sample(
            lambda r: not is_compatible(r) and r.max_authors > 50,
            "INCOMPATIBLE au-delà de 50 (bruit de désalignement)",
        )
        sample(
            lambda r: not is_compatible(r) and r.max_authors <= 50,
            "INCOMPATIBLE sous 50 (bruit déjà inclus)",
        )
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
