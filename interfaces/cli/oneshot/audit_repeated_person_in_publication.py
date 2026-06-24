"""Audit (lecture seule) — une même personne rattachée à ≥2 signatures d'une même source_publication.

Une personne ne peut pas signer deux positions d'un même enregistrement source : un
`person_id` porté par ≥2 `source_authorships` d'une même `source_publication` prouve qu'**une**
de ces signatures est mal rattachée. Le détecteur localise les couples ancre/intrus que le
scan par identifiant (`remediate_identifier_name_incompatible`) ne voit pas — notamment les
double-accroches nées d'un match par **forme de nom** (sans identifiant fautif).

Le départage s'appuie sur le **statut des formes de nom** (le verrou de l'étape 2), pas sur le
nom canonique seul : ce dernier est trop grossier (il rejette à tort « Pm Llorca » — initiales
collées d'une forme confirmée — ou « S. Porteboeuf » — nom composé). Une occurrence est
**légitime** si son nom est compatible (`names_compatible`, par tokens) avec une forme
**`confirmed`** de la personne ; **intrus** sinon. Sur un même enregistrement, une forme
confirmée qui co-signe est l'**ancre** qui prouve que les formes non confirmées et
incompatibles sont étrangères (un vrai intrus est porté par une forme `pending` — ex. « i perez
rafols » collé à Corentin Ravoux par une méga-publi à identifiant partagé). Détacher l'intrus
équivaut à rejeter sa forme de nom corrompue.

Trois cas :

- **détachable** : ≥1 occurrence légitime (ancre confirmée) **et** ≥1 intrus → les intrus sont
  détachables d'office ;
- **doublon de signature** : toutes les occurrences sont légitimes → même personne créditée
  plusieurs fois (duplication source / désalignement de positions des méga-papers) — pas un
  détachement, problème distinct ;
- **sans ancre confirmée** : aucune occurrence ne correspond à une forme confirmée → corruption
  sans point d'appui (nom canonique absent de la publi) → à examiner.

Le « changement de nom » (nom marié non encore confirmé, ex. « Sarah Julie Porteboeuf » pour une
personne « Porteboeuf-Houssais ») reste un faux positif possible du bucket détachable : à lever
par confirmation humaine (UI), pas à détacher en aveugle.

Deux phases pour ne pas streamer toute la table dans Python : aucun index ne couvre le couple
`(source_publication_id, person_id)`, mais les collisions sont rares — Postgres les agrège en
une passe (`GROUP BY … HAVING count(*) >= 2`, résultat minuscule), puis on ne rapatrie les
détails que pour ces `source_publication` (là, l'unique `(source_publication_id, author_position)`
sert le `= ANY(...)`).

Rien n'est écrit.
"""

import sys
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import Connection, bindparam, text

from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine

_CANDIDATES_SQL = text("""
    SELECT source_publication_id AS spid, person_id
    FROM source_authorships
    WHERE person_id IS NOT NULL
    GROUP BY source_publication_id, person_id
    HAVING count(*) >= 2
""")

_OCCURRENCES_SQL = text("""
    SELECT sa.source_publication_id AS spid,
           sa.person_id,
           sa.source::text AS source,
           sa.raw_author_name AS name,
           sa.author_name_normalized AS norm
    FROM source_authorships sa
    WHERE sa.source_publication_id = ANY(:spids)
      AND sa.person_id IS NOT NULL
      AND sa.author_name_normalized IS NOT NULL
""").bindparams(bindparam("spids"))


def load_person_labels(conn: Connection) -> dict[Any, str]:
    """{person_id: "Prénom Nom"}."""
    rows = conn.execute(text("SELECT id, first_name, last_name FROM persons")).all()
    return {r.id: f"{r.first_name} {r.last_name}".strip() for r in rows}


def load_confirmed_forms(conn: Connection) -> dict[Any, list[Any]]:
    """{person_id: [forme confirmée, …]} — la base du départage (verrou de l'étape 2)."""
    forms: dict[Any, list[Any]] = defaultdict(list)
    rows = conn.execute(
        text("SELECT person_id, name_form FROM person_name_forms WHERE status = 'confirmed'")
    ).all()
    for r in rows:
        forms[r.person_id].append(r.name_form)
    return forms


def is_legit(norm: str, confirmed: list[Any]) -> bool:
    """L'occurrence est-elle compatible avec une forme confirmée de la personne ?"""
    return any(names_compatible(norm, "", f, "") for f in confirmed)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    conn = get_sync_engine().connect()
    try:
        labels = load_person_labels(conn)
        confirmed = load_confirmed_forms(conn)
        print(
            f"  {len(labels)} personnes, {sum(len(v) for v in confirmed.values())} formes confirmées"
        )

        candidates = {(r.spid, r.person_id) for r in conn.execute(_CANDIDATES_SQL).all()}
        spids = sorted({spid for spid, _ in candidates})
        print(
            f"  {len(candidates)} groupes (source_publication, person_id) à ≥2 signatures, "
            f"sur {len(spids)} source_publications distinctes\n"
        )

        occ_rows = conn.execute(_OCCURRENCES_SQL, {"spids": spids}).all()
        groups = defaultdict(list)
        for r in occ_rows:
            key = (r.spid, r.person_id)
            if key in candidates:
                groups[key].append(r)

        n_detachable = n_dup = n_no_anchor = 0
        intrus_total = 0
        size_hist: dict[int, int] = defaultdict(int)
        src_by_bucket: dict[str, Counter[str]] = {
            "detachable": Counter(),
            "dup": Counter(),
            "no_anchor": Counter(),
        }
        samples: dict[str, list[Any]] = {"detachable": [], "dup": [], "no_anchor": []}

        for (spid, pid), occs in groups.items():
            size_hist[len(occs)] += 1
            src = occs[0].source  # une source_publication appartient à une seule source
            forms = confirmed.get(pid, [])
            legit = [is_legit(o.norm, forms) for o in occs]
            n_legit = sum(legit)
            label = labels.get(pid, f"#{pid}")

            if n_legit == 0:
                n_no_anchor += 1
                src_by_bucket["no_anchor"][src] += 1
                if len(samples["no_anchor"]) < 25:
                    names = ", ".join(sorted({o.name for o in occs}))
                    samples["no_anchor"].append((spid, label, names))
            elif n_legit == len(occs):
                n_dup += 1
                src_by_bucket["dup"][src] += 1
                if len(samples["dup"]) < 25:
                    names = ", ".join(sorted({o.name for o in occs}))
                    samples["dup"].append((spid, label, names))
            else:
                n_detachable += 1
                src_by_bucket["detachable"][src] += 1
                intrus = [o for o, ok in zip(occs, legit, strict=True) if not ok]
                intrus_total += len(intrus)
                if len(samples["detachable"]) < 30:
                    anchor = next(o for o, ok in zip(occs, legit, strict=True) if ok)
                    names = ", ".join(sorted({o.name for o in intrus}))
                    samples["detachable"].append((spid, label, anchor.name, names))

        print("=== départage par statut de forme de nom ===")
        print(
            f"  détachable (ancre confirmée + ≥1 intrus)     : {n_detachable} groupes, {intrus_total} intrus"
        )
        print(f"  doublon de signature (toutes légitimes)      : {n_dup}")
        print(f"  sans ancre confirmée (à examiner)            : {n_no_anchor}")
        print("\n  taille des groupes (nb signatures → nb groupes) :")
        for size in sorted(size_hist):
            print(f"    {size:3d} → {size_hist[size]}")

        sources = sorted(
            {s for c in src_by_bucket.values() for s in c}, key=lambda s: -src_by_bucket["dup"][s]
        )
        print("\n  ventilation par source (groupes) :")
        print(f"    {'source':10s} {'détach.':>8s} {'doublon':>8s} {'sans ancre':>11s}")
        for s in sources:
            print(
                f"    {s:10s} {src_by_bucket['detachable'][s]:8d} "
                f"{src_by_bucket['dup'][s]:8d} {src_by_bucket['no_anchor'][s]:11d}"
            )

        print("\n--- échantillon DÉTACHABLE (spid | personne | ancre | intrus) ---")
        for spid, label, anchor, names in samples["detachable"]:
            print(f"  {spid} | {label} | ancre={anchor!r} | intrus={names}")
        print("\n--- échantillon DOUBLON DE SIGNATURE (spid | personne | formes) ---")
        for spid, label, names in samples["dup"]:
            print(f"  {spid} | {label} | {names}")
        print("\n--- échantillon SANS ANCRE (spid | personne | formes) ---")
        for spid, label, names in samples["no_anchor"]:
            print(f"  {spid} | {label} | {names}")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
