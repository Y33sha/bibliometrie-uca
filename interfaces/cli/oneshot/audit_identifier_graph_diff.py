"""Audit (lecture seule) — diff du canal identifiant contre l'affectation courante.

Fait tourner le clustering par identifiant fort (`cluster_by_identifier`) sur le
référentiel existant, sans rien écrire ni brancher dans la cascade, et compare le
regroupement obtenu à l'affectation `source_authorships.person_id` en place. Sert à
prévisualiser ce que la première couche du record linkage ferait de différent de la
cascade append-only actuelle, avant de la substituer aux barreaux identifiant de
`decide_person_match`.

Le diff se restreint aux **identités porteuses d'un identifiant fort nu** (les seules
que le canal identifiant touche) : les signatures rattachées par le seul canal nominal
restent hors champ. Chaque composante d'identités est confrontée à l'ensemble des
`person_id` que portent aujourd'hui ses signatures, et classée :

- **Regroupement (fusion)** : la composante réunit ≥2 personnes aujourd'hui distinctes
  que le graphe unifierait.
- **Conflit noyau** : la composante ponte ≥2 personnes détentrices d'un identifiant
  (`anchor_person_ids`) — doublon franc ou erreur d'attribution à arbitrer, jamais à
  fusionner d'office.
- **Protégé par cannot-link** : fusion que `distinct_persons` empêche.
- **Éclatement (scission)** : une personne dont les identités identifiant-ancrées se
  répartissent sur ≥2 composantes, que le graphe séparerait.
- **Incarnation nouvelle** : composante dont aucune signature n'est rattachée
  aujourd'hui — un rattachement que la cascade n'a pas encore fait.

Le rapport est écrit en markdown (chemin en argument, défaut sous le répertoire temp).
Rien n'est écrit en base.
"""

import os
import sys
import tempfile
from collections import defaultdict
from itertools import combinations

from sqlalchemy import Connection, text

from domain.persons.identifier_graph import cluster_by_identifier
from infrastructure.db.engine import get_sync_engine
from infrastructure.queries.pipeline.persons_identifier_graph import (
    fetch_identifier_candidates,
)

SAMPLE_LIMIT = 40


def load_current_mapping(
    conn: Connection,
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """Affectation courante au grain identité, dans les deux sens.

    Renvoie `(identity_id -> {person_id}, person_id -> {identity_id})` pour toutes les
    signatures rattachées (`person_id` non nul). Une identité peut porter plusieurs
    `person_id` : c'est précisément le symptôme d'éclatement que la cascade produit.
    """
    identity_to_pids: dict[int, set[int]] = defaultdict(set)
    pid_to_identities: dict[int, set[int]] = defaultdict(set)
    rows = conn.execute(
        text("""
            SELECT DISTINCT identity_id, person_id
            FROM source_authorships
            WHERE person_id IS NOT NULL AND identity_id IS NOT NULL
        """)
    )
    for r in rows:
        identity_to_pids[r.identity_id].add(r.person_id)
        pid_to_identities[r.person_id].add(r.identity_id)
    return identity_to_pids, pid_to_identities


def load_person_labels(conn: Connection) -> dict[int, str]:
    """{person_id: "Prénom Nom"} pour l'étiquetage des échantillons."""
    rows = conn.execute(text("SELECT id, first_name, last_name FROM persons")).all()
    return {r.id: f"{r.first_name or ''} {r.last_name or ''}".strip() or f"#{r.id}" for r in rows}


def load_cannot_link(conn: Connection) -> set[frozenset[int]]:
    """Paires `distinct_persons` sous forme d'ensembles non ordonnés."""
    rows = conn.execute(text("SELECT person_id_a, person_id_b FROM distinct_persons")).all()
    return {frozenset((r.person_id_a, r.person_id_b)) for r in rows}


def load_identity_create_eligibility(conn: Connection) -> dict[int, bool]:
    """{identity_id: une signature autorise-t-elle la création d'une personne ?}.

    Une composante ne peut incarner une **nouvelle** personne que si au moins une de ses
    signatures y est éligible : in-périmètre (un nom hors-périmètre ne crée jamais) **et**
    autorisée par `allow_person_creation` — laquelle exclut les rôles non-auteur des thèses
    (jurys, directeurs, rapporteurs : matchables mais jamais créés). Le prédicat SQL reprend
    exactement cette règle (`domain.persons.creation.allow_person_creation`).
    """
    rows = conn.execute(
        text("""
            SELECT identity_id,
                   bool_or(
                       in_perimeter
                       AND NOT (source = 'theses'
                                AND NOT ('author' = ANY(COALESCE(roles, ARRAY['author']))))
                   ) AS eligible
            FROM source_authorships
            WHERE identity_id IS NOT NULL
            GROUP BY identity_id
        """)
    ).all()
    return {r.identity_id: bool(r.eligible) for r in rows}


def _label(pid: int, labels: dict[int, str]) -> str:
    return f"{labels.get(pid, f'#{pid}')} (#{pid})"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    out_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(tempfile.gettempdir(), "rapport_record_linkage_identifiant.md")
    )

    conn = get_sync_engine().connect()
    try:
        print("Chargement des candidats du canal identifiant...")
        candidates = fetch_identifier_candidates(conn)
        identity_name = {c.identity_id: c.identity_name for c in candidates}
        print(f"  {len(candidates)} lignes candidates, {len(identity_name)} identités")

        print("Clustering...")
        components = cluster_by_identifier(candidates)
        print(f"  {len(components)} composantes")

        print("Chargement de l'affectation courante et du cannot-link...")
        identity_to_pids, pid_to_identities = load_current_mapping(conn)
        labels = load_person_labels(conn)
        cannot_link = load_cannot_link(conn)
        create_eligible = load_identity_create_eligibility(conn)

        # Index identité -> composante, pour détecter les éclatements.
        component_of: dict[int, int] = {}
        for idx, comp in enumerate(components):
            for iid in comp.identity_ids:
                component_of[iid] = idx

        # ── Classement des composantes ─────────────────────────────
        # Chaque entrée : (composante, {person_id courants de ses signatures}).
        fusions: list = []
        noyau_conflicts: list = []
        cannot_link_protected: list = []
        # Composantes sans aucune signature rattachée aujourd'hui, selon qu'elles
        # pourraient ou non incarner une **nouvelle** personne (in-périmètre + création
        # autorisée). Les autres — co-auteurs externes, rôles non-auteur des thèses —
        # restent orphelines : jamais de fiche créée, elles ne polluent pas le référentiel.
        incarnation_candidates = 0
        never_incarnated = 0
        stable = 0
        multi_identity_components = 0

        for comp in components:
            if len(comp.identity_ids) > 1:
                multi_identity_components += 1
            cur: set[int] = set()
            for iid in comp.identity_ids:
                cur |= identity_to_pids.get(iid, set())
            anchors = comp.anchor_person_ids

            if len(cur) >= 2:
                has_cl = any(frozenset((a, b)) in cannot_link for a, b in combinations(cur, 2))
                if has_cl:
                    cannot_link_protected.append((comp, cur))
                elif len(anchors) >= 2:
                    noyau_conflicts.append((comp, cur))
                else:
                    fusions.append((comp, cur))
            elif len(cur) == 1:
                stable += 1
            elif any(create_eligible.get(iid) for iid in comp.identity_ids):
                incarnation_candidates += 1
            else:
                never_incarnated += 1

        # ── Éclatements : personnes réparties sur ≥2 composantes ───
        scissions: list[tuple[int, set[int]]] = []
        for pid, identities in pid_to_identities.items():
            comps_touched = {component_of[iid] for iid in identities if iid in component_of}
            if len(comps_touched) >= 2:
                scissions.append((pid, comps_touched))

        # ── Rapport markdown ───────────────────────────────────────
        lines: list[str] = []
        w = lines.append

        w("# Diff du canal identifiant contre l'affectation courante\n")
        w(
            "Clustering par identifiant fort gardé (`cluster_by_identifier`) confronté à "
            "`source_authorships.person_id`, sur les seules identités porteuses d'un "
            "identifiant fort. Lecture seule, rien n'est écrit ni branché.\n"
        )

        w("## Ordres de grandeur\n")
        w(f"- Identités candidates : **{len(identity_name)}**")
        w(
            f"- Composantes : **{len(components)}** (dont {multi_identity_components} à ≥2 identités)"
        )
        w(f"- Composantes stables (1 personne courante) : **{stable}**")
        w(f"- **Regroupements (fusions)** : **{len(fusions)}**")
        w(f"- **Conflits noyau** (≥2 personnes ancrées pontées) : **{len(noyau_conflicts)}**")
        w(f"- **Protégés par cannot-link** : **{len(cannot_link_protected)}**")
        w(f"- **Éclatements (scissions)** : **{len(scissions)}**")
        w(
            f"- Incarnations candidates (in-périmètre + création autorisée, aucune signature "
            f"rattachée aujourd'hui) : **{incarnation_candidates}**"
        )
        w(
            f"- Non rattachées jamais incarnées (co-auteurs externes, rôles non-auteur des "
            f"thèses) : **{never_incarnated}** — restent orphelines, hors référentiel\n"
        )

        def fusion_size_hist(bucket: list) -> str:
            hist: dict[int, int] = defaultdict(int)
            for _comp, cur in bucket:
                hist[len(cur)] += 1
            return ", ".join(f"{n} pers.→{hist[n]}" for n in sorted(hist))

        w("## Regroupements (fusions)\n")
        w(
            "Composantes réunissant ≥2 personnes aujourd'hui distinctes, sans conflit "
            "d'ancres ni cannot-link. C'est l'effet principal attendu du passage en graphe : "
            "ce que la cascade append-only a éparpillé faute de recalculer le regroupement.\n"
        )
        if fusions:
            w(f"Répartition par nombre de personnes réunies : {fusion_size_hist(fusions)}\n")
            w("Échantillon (personnes que la composante unifierait) :\n")
            for comp, cur in sorted(fusions, key=lambda x: -len(x[1]))[:SAMPLE_LIMIT]:
                names = " | ".join(_label(pid, labels) for pid in sorted(cur))
                forms = ", ".join(sorted({identity_name.get(i, "?") for i in comp.identity_ids}))
                w(f"- {names}  \n  _formes_ : {forms}")
            w("")

        w("## Conflits noyau (≥2 personnes ancrées pontées)\n")
        w(
            "La composante ponte ≥2 personnes détentrices d'un identifiant fort. Soit deux "
            "fiches d'une même personne (doublon franc), soit un identifiant qui a traîné une "
            "signature étrangère (erreur d'attribution). À arbitrer, jamais à fusionner d'office.\n"
        )
        for comp, _cur in noyau_conflicts[:SAMPLE_LIMIT]:
            anchors = " | ".join(_label(pid, labels) for pid in comp.anchor_person_ids)
            forms = ", ".join(sorted({identity_name.get(i, "?") for i in comp.identity_ids}))
            w(f"- ancres : {anchors}  \n  _formes_ : {forms}")
        w("")

        w("## Protégés par cannot-link\n")
        w(
            "Fusions que `distinct_persons` empêche : la composante réunirait des personnes "
            "explicitement marquées distinctes. Le graphe respecte la décision humaine.\n"
        )
        for _comp, cur in cannot_link_protected[:SAMPLE_LIMIT]:
            names = " | ".join(_label(pid, labels) for pid in sorted(cur))
            w(f"- {names}")
        w("")

        w("## Éclatements (scissions)\n")
        w(
            "Personnes dont les identités identifiant-ancrées se répartissent sur ≥2 "
            "composantes : le graphe les séparerait. Deux cas se mêlent — une fiche ayant "
            "absorbé les signatures (et souvent les identifiants) d'un homonyme ou d'un "
            "co-auteur, que les identifiants démêlent (vraie séparation) ; ou une même "
            "personne dont les formes ne partagent aucune valeur d'identifiant pontante "
            "(variante, coquille), que le matching par nom rejoindra plus tard (sur-séparation "
            "propre au canal identifiant seul).\n"
        )
        person_identities = {pid: ids for pid, ids in pid_to_identities.items()}
        for pid, comps_touched in sorted(scissions, key=lambda x: -len(x[1]))[:SAMPLE_LIMIT]:
            own = person_identities[pid]
            groups = []
            for cidx in sorted(comps_touched):
                # Les identités de cette personne présentes dans la composante.
                forms = sorted(
                    {identity_name.get(i, "?") for i in components[cidx].identity_ids if i in own}
                )
                groups.append("{" + ", ".join(forms) + "}")
            w(f"- {_label(pid, labels)} → {' vs '.join(groups)}")
        w("")

        report = "\n".join(lines)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nRapport écrit : {out_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
