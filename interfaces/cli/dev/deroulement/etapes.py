"""Blocs du déroulement du pipeline, leurs étapes, leurs affluents et sorties, et les tâches du code rangées dans chacun.

Un bloc du circuit principal se découpe en étapes. Un affluent alimente une étape ; une sortie dérive d'une étape. Un affluent se découpe aussi en étapes, et une étape en sous-étapes. Chaque groupe de tâches a un libellé facultatif, nom de phase ou d'étape du code.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pipeline.phases import ALL_TASKS

_TASKS = [t.name for t in ALL_TASKS]


class Group(TypedDict):
    """Tâches affichées sur une ligne, après leur libellé."""

    label: str | None
    tasks: list[str]


class Step(TypedDict):
    """Étape d'un bloc ou d'un affluent. Une étape à sous-étapes est sans groupe de tâches."""

    id: str
    title: str | None
    text: str | None
    groups: list[Group]
    steps: list[Step]


class Node(TypedDict):
    """Bloc du circuit principal. Un bloc à une seule étape sans titre est indivisible."""

    id: str
    num: str | None
    title: str
    role: str
    steps: list[Step]
    technical: NotRequired[bool]


class Affluent(TypedDict):
    """Affluent (`in`) ou sortie (`out`) d'une étape, avec ses tâches ou ses étapes."""

    id: str
    kind: Literal["in", "out"]
    title: str
    text: str
    feeds: list[str]
    groups: NotRequired[list[Group]]
    steps: NotRequired[list[Step]]


class Layout(TypedDict):
    """Grille sur grand écran (rail gauche, deux colonnes centrales, rail droit) ; `order` donne l'ordre sur une colonne."""

    areas: list[str]
    rails: dict[str, list[str]]
    order: list[str]


Edge = TypedDict(
    "Edge",
    {
        "from": str,
        "to": str,
        "kind": Literal["main", "aff"],
        "route": Literal["v", "h", "rail", "lane"],
        "lane": NotRequired[int],
        "dy": NotRequired[int],
    },
)
"""Lien tracé entre deux éléments de la page : `v` vertical entre blocs, `h` horizontal vers un rail, `rail` vertical dans un rail, `lane` par le couloir entre un rail et le centre."""


def phase(name: str, *, only: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> list[str]:
    """Renvoie les tâches de la phase dans l'ordre d'exécution, restreintes à `only` ou privées de `exclude` (noms courts)."""
    tasks = [t for t in _TASKS if t.startswith(f"{name}.")]
    if only:
        tasks = [f"{name}.{s}" for s in only]
    return [t for t in tasks if t.split(".", 1)[1] not in exclude]


def group(tasks: list[str], label: str | None = None) -> Group:
    return {"label": label, "tasks": tasks}


def step(
    step_id: str,
    title: str | None,
    text: str | None,
    groups: list[Group] | None = None,
    steps: list[Step] | None = None,
) -> Step:
    return {
        "id": step_id,
        "title": title,
        "text": text,
        "groups": groups or [],
        "steps": steps or [],
    }


NORMALIZE_SOURCES = phase(
    "normalize",
    exclude=(
        "withhold_openalex_authors",
        "prune_disappeared",
        "cleanup_orphan_contributor_information",
        "cleanup_orphan_addresses",
        "arbitrate_identifiers",
    ),
)

NODES: list[Node] = [
    {
        "id": "n1",
        "num": "1",
        "title": "Moissonnage",
        "role": "Interroge les sources et garde les documents tels quels.",
        "steps": [
            step(
                "s1-1",
                "Recherche par affiliation",
                "Documents qui mentionnent une structure du périmètre.",
                [group(phase("harvest"), "harvest")],
            ),
            step(
                "s1-2",
                "Recherche par personne",
                "Documents des personnes RH, par ORCID, idHAL et IdRef.",
                [group(phase("harvest_by_person"), "harvest_by_person")],
            ),
            step(
                "s1-3",
                "Recherche croisée",
                "Documents trouvés dans une autre source : hal-id, NNT, brevet, DOI.",
                [group(phase("fetch_missing"), "fetch_missing")],
            ),
            step(
                "s1-4",
                "Mise à jour",
                "Documents non revus, disparus, ou aux auteurs tronqués.",
                [
                    group(phase("fetch_stale"), "fetch_stale"),
                    group(phase("fetch_truncated"), "fetch_truncated"),
                ],
            ),
        ],
    },
    {
        "id": "n2",
        "num": "2",
        "title": "Normalisation",
        "role": "Passage du JSON au SQL : enregistrements sources, contributions sources, adresses.",
        "steps": [
            step(
                "s2-1",
                None,
                None,
                [
                    group(NORMALIZE_SOURCES, "par source"),
                    group(
                        [t for t in phase("normalize") if t not in NORMALIZE_SOURCES], "nettoyage"
                    ),
                ],
            ),
        ],
    },
    {
        "id": "n3",
        "num": "3",
        "title": "Affiliations",
        "role": "Relie les contributions sources aux structures et repère celles du périmètre.",
        "steps": [
            step(
                "s3-1",
                "Reconnaissance des structures",
                "Noms de structures dans les adresses et les partenaires de thèse.",
                [group(phase("affiliations", exclude=("decide_source_contribution_perimeter",)))],
            ),
            step(
                "s3-2",
                "Décision du périmètre",
                "Par une structure du périmètre, ou l'identifiant d'une personne RH.",
                [group(phase("affiliations", only=("decide_source_contribution_perimeter",)))],
            ),
        ],
    },
    {
        "id": "n4",
        "num": "4",
        "title": "Métadonnées",
        "role": "Corrige les métadonnées pour la réconciliation et la consolidation.",
        "steps": [
            step(
                "s4-1",
                "Correction des enregistrements",
                "Type de document, identifiants des dépôts HAL introuvables.",
                [group(phase("metadata_correction", only=("correct_source_records",)))],
            ),
            step(
                "s4-2",
                "Nettoyage des DOI",
                "Cibles des DOI secondaires, retrait des DOI partagés ou inconnus.",
                [group(phase("metadata_correction", only=("doi_targets", "remove_identifiers")))],
            ),
            step(
                "s4-3",
                "Admission à la réconciliation",
                "Enregistrements sources écartés de la réconciliation.",
                [group(phase("metadata_correction", only=("decide_matchability",)))],
            ),
        ],
    },
    {
        "id": "n5",
        "num": "5",
        "title": "Publications",
        "role": "Réconcilie les enregistrements sources et constitue le référentiel des publications.",
        "steps": [
            step(
                "s5-1",
                "Réconciliation",
                "Même document : DOI, NNT, hal-id, ou type, titre et année.",
                [group(phase("publications", only=("reconcile",)))],
            ),
            step(
                "s5-2",
                "Consolidation",
                "Métadonnées de chaque publication, tirées de ses enregistrements sources.",
                [group(phase("publications", only=("consolidate_publications",)))],
            ),
        ],
    },
    {
        "id": "n6",
        "num": "6",
        "title": "Personnes",
        "role": "Attribue les contributions aux personnes et constitue le référentiel des personnes.",
        "steps": [
            step(
                "s6-1",
                "Alignement des auteurs",
                "Les contributions sources d'un même auteur forment une contribution.",
                [group(phase("author_grouping"))],
            ),
            step(
                "s6-2",
                "Attribution",
                "Par identifiant ou par forme de nom.",
                [group(phase("persons"))],
            ),
            step(
                "s6-3",
                "Attributions suspectes",
                "Publications probablement signées par un homonyme.",
                [group(phase("suspect_attributions"))],
            ),
        ],
    },
    {
        "id": "nF",
        "num": None,
        "title": "Finalisation",
        "role": "Purges, données dérivées, compteurs.",
        "technical": True,
        "steps": [
            step(
                "sF-1",
                "Purges",
                "Publications sans enregistrement source ou sans personne, référentiels éditoriaux vides.",
                [
                    group(
                        phase(
                            "finalize",
                            only=(
                                "purge_publications",
                                "delete_empty_monographs",
                                "delete_empty_serials",
                                "delete_empty_publishers",
                            ),
                        )
                    )
                ],
            ),
            step(
                "sF-2",
                "Données dérivées",
                "Périmètre des publications, liens aux structures, éditeur des revues.",
                [
                    group(
                        phase(
                            "finalize",
                            only=(
                                "publications_in_perimeter",
                                "refresh_structure_views",
                                "serial_publishers",
                            ),
                        )
                    )
                ],
            ),
            step(
                "sF-3",
                "Compteurs",
                "Publications des adresses, revues et éditeurs, usage des sujets.",
                [group(phase("finalize", only=("publication_counts", "count_subject_usage")))],
            ),
        ],
    },
]

AFFLUENTS: list[Affluent] = [
    {
        "id": "a-per",
        "kind": "in",
        "title": "Structures du périmètre",
        "text": "Structures de chaque périmètre.",
        "groups": [group(["perimeter_structures"])],
        "feeds": ["Recherche par affiliation", "Décision du périmètre"],
    },
    {
        "id": "a-str",
        "kind": "in",
        "title": "Référentiels de structures",
        "text": "ROR et structures HAL à jour.",
        "groups": [group(phase("structures"), "structures")],
        "feeds": ["Décision du périmètre", "Pays"],
    },
    {
        "id": "a-doi",
        "kind": "in",
        "title": "Résolution des DOI",
        "text": "Agence des préfixes, existence et URL des DOI chez doi.org.",
        "groups": [group(phase("dois"), "dois")],
        "feeds": ["Éditeurs", "Nettoyage des DOI"],
    },
    {
        "id": "a-edi",
        "kind": "in",
        "title": "Référentiels éditoriaux",
        "text": "Éditeurs, revues et monographies des enregistrements sources.",
        "steps": [
            step(
                "e-pub",
                "Éditeurs",
                "Titulaire de chaque préfixe DOI, puis éditeur de chaque enregistrement source.",
                [
                    group(
                        phase(
                            "publishing",
                            only=(
                                "resolve_crossref_publishers",
                                "resolve_datacite_publishers",
                                "attach_publishers",
                                "merge_duplicate_publishers",
                            ),
                        )
                    )
                ],
            ),
            step(
                "e-ser",
                "Revues",
                None,
                steps=[
                    step(
                        "e-ser-1",
                        "Rattachement",
                        "Par ISSN-L, identifiant OpenAlex ou titre.",
                        [
                            group(
                                phase(
                                    "publishing",
                                    only=(
                                        "sync_issns",
                                        "check_issns_in_sudoc",
                                        "import_issnl_table",
                                        "attach_serials",
                                    ),
                                )
                            )
                        ],
                    ),
                    step(
                        "e-ser-2",
                        "Qualification",
                        "Type, DOAJ, modèle open access.",
                        [
                            group(
                                phase(
                                    "publishing",
                                    only=(
                                        "check_serials_in_openalex",
                                        "type_proceedings_serials",
                                        "type_journal_serials",
                                        "enrich_serials_from_doaj",
                                        "model_serials",
                                    ),
                                )
                            )
                        ],
                    ),
                    step(
                        "e-ser-3",
                        "Revue par le DOI",
                        "Revue manquante retrouvée par l'espace de noms DOI.",
                        [
                            group(
                                phase(
                                    "publishing",
                                    only=("learn_serial_doi_namespaces", "serial_by_doi"),
                                )
                            )
                        ],
                    ),
                ],
            ),
            step(
                "e-mon",
                "Monographies",
                "Monographie et collection de chaque volume, volumes d'actes.",
                [
                    group(
                        phase(
                            "publishing",
                            only=(
                                "attach_monographs",
                                "link_monographs_to_collections",
                                "type_proceedings_volumes",
                            ),
                        )
                    )
                ],
            ),
        ],
        "feeds": ["Correction des enregistrements"],
    },
    {
        "id": "a-pay",
        "kind": "in",
        "title": "Pays",
        "text": "Pays des adresses, reportés sur les enregistrements sources.",
        "groups": [group(phase("countries"), "countries")],
        "feeds": ["Consolidation"],
    },
    {
        "id": "a-rel",
        "kind": "out",
        "title": "Relations",
        "text": "Versions, errata, rétractations.",
        "groups": [group(phase("relations"), "relations")],
        "feeds": [],
    },
    {
        "id": "a-oa",
        "kind": "out",
        "title": "Open access",
        "text": "Verdict d'Unpaywall, statut open access.",
        "groups": [group(phase("open_access"), "open_access")],
        "feeds": [],
    },
    {
        "id": "a-sub",
        "kind": "out",
        "title": "Sujets",
        "text": "Sujets des sources, reportés sur les publications.",
        "groups": [group(phase("subjects"), "subjects")],
        "feeds": ["Attributions suspectes"],
    },
]

LAYOUT: Layout = {
    "areas": [
        "r-a1 n1 n1 .",
        ". n2 n2 .",
        "r-a3 n3 n4 r-b3",
        "r-a5 n5 n5 r-b5",
        ". n6 n6 .",
        ". nF nF .",
    ],
    "rails": {
        "r-a1": ["a-per"],
        "r-a3": ["a-str"],
        "r-b3": ["a-doi", "a-edi"],
        "r-a5": ["a-pay"],
        "r-b5": ["a-rel", "a-oa", "a-sub"],
    },
    "order": ["r-a1", "n1", "n2", "r-a3", "n3", "r-b3", "n4", "r-a5", "n5", "r-b5", "n6", "nF"],
}

EDGES: list[Edge] = [
    {"from": "n1", "to": "n2", "kind": "main", "route": "v"},
    {"from": "n2", "to": "n3", "kind": "main", "route": "v"},
    {"from": "n2", "to": "n4", "kind": "main", "route": "v"},
    {"from": "n3", "to": "n5", "kind": "main", "route": "v"},
    {"from": "n4", "to": "n5", "kind": "main", "route": "v"},
    {"from": "n5", "to": "n6", "kind": "main", "route": "v"},
    {"from": "n6", "to": "nF", "kind": "main", "route": "v"},
    {"from": "a-per", "to": "s1-1", "kind": "aff", "route": "h"},
    {"from": "a-per", "to": "s3-2", "kind": "aff", "route": "lane", "lane": -10},
    {"from": "a-str", "to": "s3-2", "kind": "aff", "route": "h", "dy": 18},
    {"from": "a-str", "to": "a-pay", "kind": "aff", "route": "rail"},
    {"from": "a-doi", "to": "a-edi", "kind": "aff", "route": "rail"},
    {"from": "a-doi", "to": "s4-2", "kind": "aff", "route": "h"},
    {"from": "a-edi", "to": "s4-1", "kind": "aff", "route": "h"},
    {"from": "a-pay", "to": "s5-2", "kind": "aff", "route": "h"},
    {"from": "s5-2", "to": "a-rel", "kind": "aff", "route": "h"},
    {"from": "s5-2", "to": "a-oa", "kind": "aff", "route": "h"},
    {"from": "s5-2", "to": "a-sub", "kind": "aff", "route": "h"},
    {"from": "a-sub", "to": "s6-3", "kind": "aff", "route": "lane", "lane": 0},
]


def _leaves(steps: list[Step]) -> list[Step]:
    """Renvoie les étapes porteuses de tâches : les étapes sans sous-étape, et les sous-étapes."""
    return [leaf for s in steps for leaf in (_leaves(s["steps"]) if s["steps"] else [s])]


def placed_tasks() -> list[str]:
    """Renvoie les tâches rangées dans les blocs et les affluents, dans l'ordre de la page."""
    groups = [g for n in NODES for s in _leaves(n["steps"]) for g in s["groups"]]
    for a in AFFLUENTS:
        groups += a.get("groups", []) + [
            g for s in _leaves(a.get("steps", [])) for g in s["groups"]
        ]
    return [t for g in groups for t in g["tasks"]]


def placement_problems() -> list[str]:
    """Renvoie les tâches du pipeline rangées zéro ou plusieurs fois, et les tâches rangées inconnues du pipeline."""
    placed = placed_tasks()
    doubles = sorted({t for t in placed if placed.count(t) > 1})
    unknown = sorted(set(placed) - set(_TASKS))
    missing = [t for t in _TASKS if t not in placed]
    return (
        [f"tâche rangée plusieurs fois : {t}" for t in doubles]
        + [f"tâche inconnue du pipeline : {t}" for t in unknown]
        + [f"tâche non rangée : {t}" for t in missing]
    )
