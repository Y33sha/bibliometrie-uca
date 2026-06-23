"""Audit (lecture seule) — formes de nom ambiguës (une forme portée par ≥2 personnes).

Seconde source de paires candidates du moteur de dédoublonnage (étape 3 du chantier
`DATA_personnes-dedoublonnage-assiste`), plus volumineuse et plus bruitée que les liens
par identifiant (les homonymes légitimes y abondent). On restreint aux formes ayant **au
moins un lien `pending`** : les liens déjà tranchés (`confirmed`/`rejected`) sortent du
travail à faire.

Pour chaque forme ambiguë, on regarde si elle est **compatible** (`names_compatible`)
avec le nom canonique de chaque personne qui la porte :

- au moins une personne **incompatible** → la forme y est probablement intruse (erreur
  d'attribution) → candidate au `rejected` ;
- toutes compatibles, ≥2 personnes → **homonymie** (formes à `confirmed` sur chacune) ou
  **doublon** (à fusionner) — le départage demande les recouvrements (co-auteurs/labos),
  hors de cet audit.

Rien n'est écrit.
"""

import sys
from collections import defaultdict

from sqlalchemy import text

from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine


def load_person_names(conn):
    """{person_id: (last_name_normalized, first_name_normalized, "Prénom Nom")}."""
    rows = conn.execute(
        text("""
            SELECT id, last_name_normalized AS ln, first_name_normalized AS fn,
                   first_name, last_name
            FROM persons
        """)
    ).all()
    return {r.id: (r.ln or "", r.fn or "", f"{r.first_name} {r.last_name}".strip()) for r in rows}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = get_sync_engine().connect()
    try:
        names = load_person_names(conn)

        rows = conn.execute(
            text("""
                SELECT name_form,
                       array_agg(person_id ORDER BY person_id) AS pids,
                       array_agg(status::text ORDER BY person_id) AS statuses
                FROM person_name_forms
                GROUP BY name_form
                HAVING count(*) >= 2 AND bool_or(status = 'pending')
            """)
        ).all()
        print(f"  {len(rows)} formes ambiguës (≥2 personnes, ≥1 lien pending)\n")

        size_hist = defaultdict(int)
        with_error = []  # forme intruse sur ≥1 personne
        all_compatible = []  # homonymie / doublon
        n_with_error = 0
        n_all_compat = 0

        for r in rows:
            size_hist[len(r.pids)] += 1
            compat_flags = [
                names_compatible(
                    r.name_form,
                    "",
                    names.get(pid, ("", "", ""))[0],
                    names.get(pid, ("", "", ""))[1],
                )
                for pid in r.pids
            ]
            labels = ", ".join(
                f"{names.get(pid, ('', '', f'#{pid}'))[2]}{'' if ok else ' [✗]'}"
                for pid, ok in zip(r.pids, compat_flags)
            )
            if not all(compat_flags):
                n_with_error += 1
                if len(with_error) < 30:
                    with_error.append((r.name_form, labels))
            else:
                n_all_compat += 1
                if len(all_compatible) < 30:
                    all_compatible.append((r.name_form, labels))

        print("=== répartition ===")
        print(f"  avec ≥1 personne incompatible (erreur probable) : {n_with_error}")
        print(f"  toutes compatibles (homonymie ou doublon)       : {n_all_compat}")
        print("\n  taille (nb personnes → nb formes) :")
        for size in sorted(size_hist):
            print(f"    {size:3d} → {size_hist[size]}")

        print("\n--- échantillon AVEC ERREUR (forme | personnes, [✗]=incompatible) ---")
        for form, labels in with_error:
            print(f"  {form!r:28s} | {labels}")
        print("\n--- échantillon TOUTES COMPATIBLES (homonymie/doublon : forme | personnes) ---")
        for form, labels in all_compatible:
            print(f"  {form!r:28s} | {labels}")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
