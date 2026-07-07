"""Audit (lecture seule) — nom-autorité consensuel vs attribution existante.

Outille la décision du canal identifiant recalculable (chantier
`DATA_persons-cascade-ordre-independante`, Phase 1). Pour chaque valeur
d'identifiant fort (orcid / idref / hal_person_id, hors `_dubious`), calcule le
**nom-autorité consensuel** — la pluralité des `(nom, prénom)` normalisés des
`source_authorships` portant la valeur — et le confronte au nom du **propriétaire
actuel** (`person_identifiers` non rejeté, le premier arrivé qui a capté la
valeur).

L'enjeu mesuré : combien de valeurs voient leur consensus **contredire** le
propriétaire (nom-autorité incompatible avec le nom de la personne à qui la
valeur est aujourd'hui attribuée), et de quelle nature sont ces contradictions.
On sépare :

- le **statut du propriétaire** (`confirmed` = attribution verrouillée admin, à
  ne jamais toucher ; `pending` = candidate au re-pointage) ;
- la **nature de l'écart**, objectivée par les tokens pleins partagés entre le nom
  du propriétaire et le consensus (initiales exclues, car elles collisionnent
  trivialement) : **aucun token commun** signe une capture franche (deux personnes
  sans rapport) ; **patronyme commun, prénom différent** un homonyme ou une
  variante de prénom ; **prénom commun, patronyme différent** un nom marié /
  changement de nom de la même personne.

`names_compatible` du domaine tranche la compatibilité, pour coller au
comportement réel de la cascade. Rien n'est écrit.
"""

import sys
from collections import Counter, defaultdict

from sqlalchemy import Connection, text

from domain.normalize import normalize_name
from domain.persons.matching import ORCID_MATCH_SOURCES
from domain.persons.name_matching import names_compatible, parse_raw_author_name
from infrastructure.db.engine import get_sync_engine

ID_TYPES = ("orcid", "idref", "hal_person_id")


def full_tokens(*parts: str) -> set[str]:
    """Tokens pleins (≥2 caractères) des fragments de nom. Les initiales, qui
    collisionnent trivialement (« m » de « m della pietra » et « m delmastro »),
    sont exclues : un token partagé n'a de sens discriminant que s'il est plein."""
    return {tok for part in parts for tok in part.split() if len(tok) >= 2}


def levenshtein(a: str, b: str) -> int:
    """Distance d'édition (insertions / suppressions / substitutions)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def load_owner_map(conn: Connection, id_type: str) -> dict[str, tuple[int, str, str, str]]:
    """`{id_value: (person_id, last_norm, first_norm, status)}` — propriétaire
    actuel de la valeur (non rejeté) et statut d'attribution."""
    rows = conn.execute(
        text("""
            SELECT pi.id_value, pi.person_id, pi.status,
                   p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = :t AND pi.status <> 'rejected'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.ln or "", r.fn or "", r.status) for r in rows}


def consensus(names: Counter[tuple[str, str]]) -> tuple[str, str]:
    """Nom-autorité : le `(nom, prénom)` normalisé le plus porté ; départage
    déterministe (compte décroissant, puis ordre lexicographique)."""
    return min(names.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    conn = get_sync_engine().connect()
    try:
        owners = {t: load_owner_map(conn, t) for t in ID_TYPES}
        for t in ID_TYPES:
            print(f"  map {t}: {len(owners[t])} valeurs attribuées")

        # Distribution des noms des porteurs par valeur, et personnes rattachées.
        names_by_value: dict[tuple[str, str], Counter[tuple[str, str]]] = defaultdict(Counter)
        persons_by_value: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
        result = conn.execution_options(stream_results=True).execute(
            text("""
                SELECT sa.source::text AS source,
                       sa.person_id,
                       sa.raw_author_name AS name,
                       aik.person_identifiers->>'orcid' AS orcid,
                       aik.person_identifiers->>'idref' AS idref,
                       aik.person_identifiers->>'hal_person_id' AS hal_person_id
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.raw_author_name IS NOT NULL
                  AND (aik.person_identifiers ? 'orcid'
                       OR aik.person_identifiers ? 'idref'
                       OR aik.person_identifiers ? 'hal_person_id')
            """)
        )
        n = 0
        for row in result:
            n += 1
            last, first = parse_raw_author_name(row.name)
            key_name = (normalize_name(last), normalize_name(first))
            values = {"orcid": row.orcid, "idref": row.idref, "hal_person_id": row.hal_person_id}
            for t in ID_TYPES:
                val = values[t]
                if not val:
                    continue
                if t == "orcid" and row.source not in ORCID_MATCH_SOURCES:
                    continue
                names_by_value[(t, val)][key_name] += 1
                if row.person_id is not None:
                    persons_by_value[(t, val)][row.person_id] += 1
        print(f"  {n} authorships à identifiant scannées\n")

        buckets = ("CAPT", "SURN", "MARR", "OTHR", "LOCK")
        legend = {
            "CAPT": "aucun token plein commun → capture franche",
            "SURN": "patronyme commun, prénom différent → homonyme ou typo de prénom",
            "MARR": "prénom commun, patronyme différent → nom marié / changement",
            "OTHR": "recouvrement partiel autre",
            "LOCK": "attribution confirmed (verrouillée admin)",
        }
        dist_labels = ("0", "1", "2", "3", "4+")
        for t in ID_TYPES:
            resolved = agree = 0
            counts: Counter[str] = Counter()
            samples: dict[str, list[str]] = {b: [] for b in buckets}
            # Sous-analyse du bucket SURN : distance d'édition du prénom concaténé
            # (espaces retirés) — proxy pour trancher typo/concaténation (même
            # personne, distance faible) vs homonyme (prénom franchement autre).
            surn_dist: Counter[str] = Counter()
            surn_dist_samples: dict[str, list[str]] = defaultdict(list)
            for val, owner in owners[t].items():
                names = names_by_value.get((t, val))
                if not names:
                    continue  # attribuée mais aucun porteur observé (rare)
                resolved += 1
                person_id, owner_ln, owner_fn, status = owner
                cons_ln, cons_fn = consensus(names)
                if names_compatible(cons_ln, cons_fn, owner_ln, owner_fn):
                    agree += 1
                    continue
                shared_last = full_tokens(owner_ln) & full_tokens(cons_ln)
                shared_first = full_tokens(owner_fn) & full_tokens(cons_fn)
                if status == "confirmed":
                    bucket = "LOCK"
                elif not (shared_last or shared_first):
                    bucket = "CAPT"
                elif shared_last and not shared_first:
                    bucket = "SURN"
                elif shared_first and not shared_last:
                    bucket = "MARR"
                else:
                    bucket = "OTHR"
                counts[bucket] += 1
                total = sum(names.values())
                owner_count = names.get((owner_ln, owner_fn), 0)
                cons_count = names[(cons_ln, cons_fn)]
                others = sum(1 for pid in persons_by_value[(t, val)] if pid != person_id)
                line = (
                    f"      {t}:{val}  "
                    f"proprio={owner_fn} {owner_ln!r}({status},{owner_count}/{total}) "
                    f"cons={cons_fn} {cons_ln!r}({cons_count}/{total}) autres={others}"
                )
                if len(samples[bucket]) < 12:
                    samples[bucket].append(line)
                if bucket == "SURN":
                    d = levenshtein(owner_fn.replace(" ", ""), cons_fn.replace(" ", ""))
                    dlabel = str(d) if d <= 3 else "4+"
                    surn_dist[dlabel] += 1
                    if len(surn_dist_samples[dlabel]) < 8:
                        surn_dist_samples[dlabel].append(line)
            contradict = sum(counts.values())
            print(f"=== {t} ===  résolues={resolved}  compatible={agree}  contraire={contradict}")
            for b in buckets:
                print(f"    {b} : {counts[b]:4d}   ({legend[b]})")
            print(
                "      SURN par distance d'édition du prénom : "
                + "  ".join(f"d={d}:{surn_dist[d]}" for d in dist_labels)
            )
            for b in buckets:
                if samples[b]:
                    print(f"  — échantillon {b} —")
                    print("\n".join(samples[b]))
            print("  — SURN par distance de prénom —")
            for dlabel in dist_labels:
                if surn_dist_samples[dlabel]:
                    print(f"    d={dlabel} :")
                    print("\n".join(surn_dist_samples[dlabel]))
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
