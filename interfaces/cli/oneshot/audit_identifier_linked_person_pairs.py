"""Audit (lecture seule) — paires de personnes liées par un identifiant partagé.

Source de paires candidates la plus forte du moteur de dédoublonnage (étape 3 du
chantier `DATA_personnes-dedoublonnage-assiste`) : une même valeur d'identifiant brut
(orcid / idref / hal_person_id, non `_dubious`) portée par des `source_authorships`
rattachées à **plusieurs `person_id` distincts**. Chaque cluster est soit un **doublon**
(deux fiches pour la même personne), soit une **erreur d'attribution** (l'identifiant a
traîné une signature étrangère).

Le tri se lit sur les noms : un cluster dont tous les noms sont **mutuellement
compatibles** (`names_compatible`) est un doublon probable ; un cluster **mixte** (≥2
noms incompatibles) signale une contamination résiduelle. L'ORCID n'est compté que pour
les sources à dépôt auteur (`ORCID_MATCH_SOURCES`), comme dans la cascade.

Note : à lire de préférence **après** la remédiation `remediate_identifier_name_incompatible`,
qui retire les intrus nom-incompatibles à porteur légitime — ce qui reste ici est plus
proche du dédoublonnage pur.

Rien n'est écrit.
"""

import sys
from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations
from typing import Any

from sqlalchemy import Connection, text

from domain.persons.matching import ORCID_MATCH_SOURCES
from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine

ID_TYPES = ("orcid", "idref", "hal_person_id")


def load_person_names(conn: Connection) -> dict[Any, tuple[str, str, str]]:
    """{person_id: (last_name_normalized, first_name_normalized, "Prénom Nom")}."""
    rows = conn.execute(
        text("""
            SELECT id, last_name_normalized AS ln, first_name_normalized AS fn,
                   first_name, last_name
            FROM persons
        """)
    ).all()
    return {r.id: (r.ln or "", r.fn or "", f"{r.first_name} {r.last_name}".strip()) for r in rows}


def cluster_compatible(person_ids: Iterable[Any], names: dict[Any, tuple[str, str, str]]) -> bool:
    """Vrai si toutes les paires du cluster ont des noms compatibles."""
    forms = [names.get(pid, ("", "", "")) for pid in person_ids]
    return all(names_compatible(a[0], a[1], b[0], b[1]) for a, b in combinations(forms, 2))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    conn = get_sync_engine().connect()
    try:
        names = load_person_names(conn)
        print(f"  {len(names)} personnes chargées")

        # {(id_type, id_value): {person_id, ...}}
        id_to_persons = defaultdict(set)
        result = conn.execution_options(stream_results=True).execute(
            text("""
                SELECT sa.source::text AS source,
                       sa.person_id,
                       sa.person_identifiers->>'orcid' AS orcid,
                       sa.person_identifiers->>'idref' AS idref,
                       sa.person_identifiers->>'hal_person_id' AS hal_person_id
                FROM source_authorships sa
                WHERE sa.person_id IS NOT NULL
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
                id_to_persons[(t, val)].add(row.person_id)
        print(f"  {n} authorships à identifiant scannées\n")

        # Clusters multi-personnes.
        stats: dict[str, dict[str, int]] = {t: defaultdict(int) for t in ID_TYPES}
        compatible_samples: list[tuple[str, str, str]] = []
        mixed_samples: list[tuple[str, str, str]] = []
        size_hist: dict[int, int] = defaultdict(int)
        for (t, val), persons in id_to_persons.items():
            if len(persons) < 2:
                continue
            stats[t]["clusters"] += 1
            size_hist[len(persons)] += 1
            compat = cluster_compatible(persons, names)
            stats[t]["compatible" if compat else "mixed"] += 1
            bucket = compatible_samples if compat else mixed_samples
            if len(bucket) < 30:
                labels = ", ".join(
                    names.get(pid, ("", "", f"#{pid}"))[2] for pid in sorted(persons)
                )
                bucket.append((t, val, labels))

        print("=== clusters d'un identifiant porté par ≥2 personnes ===")
        for t in ID_TYPES:
            s = stats[t]
            print(
                f"  {t:14s} : {s['clusters']:6d} clusters "
                f"(compatibles={s['compatible']}, mixtes={s['mixed']})"
            )
        print("\n  taille des clusters (nb personnes → nb clusters) :")
        for size in sorted(size_hist):
            print(f"    {size:3d} → {size_hist[size]}")

        print("\n--- échantillon COMPATIBLE (doublon probable : identifiant | personnes) ---")
        for t, val, labels in compatible_samples:
            print(f"  {t}:{val} | {labels}")
        print("\n--- échantillon MIXTE (contamination probable : identifiant | personnes) ---")
        for t, val, labels in mixed_samples:
            print(f"  {t}:{val} | {labels}")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
