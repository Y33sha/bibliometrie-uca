"""Blocs du déroulement du pipeline, leurs étapes, leurs affluents et sorties, et les tâches du code rangées dans chacun.

Un bloc du circuit principal se découpe en étapes. Un affluent alimente une étape ; une sortie dérive d'une étape. Un affluent se découpe aussi en étapes, et une étape en sous-étapes. Chaque groupe de tâches a un libellé facultatif, nom de phase ou d'étape du code. Le texte d'un bloc, d'une étape ou d'un affluent dit ce que fait le pipeline. Son lien `doc` désigne un chapitre de `docs/pipeline`, avec une ancre facultative.
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
    doc: str | None


class Node(TypedDict):
    """Bloc du circuit principal. Un bloc à une seule étape sans titre est indivisible."""

    id: str
    num: str | None
    title: str
    role: str
    doc: str
    steps: list[Step]
    technical: NotRequired[bool]


class Affluent(TypedDict):
    """Affluent (`in`) ou sortie (`out`) d'une étape, avec ses tâches ou ses étapes."""

    id: str
    kind: Literal["in", "out"]
    title: str
    text: str
    feeds: list[str]
    doc: NotRequired[str]
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
    doc: str | None = None,
) -> Step:
    return {
        "id": step_id,
        "title": title,
        "text": text,
        "groups": groups or [],
        "steps": steps or [],
        "doc": doc,
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
        "role": "Interroge les sources et garde chaque document tel que la source le renvoie.",
        "doc": "02-harvest.md",
        "steps": [
            step(
                "s1-1",
                "Recherche par affiliation",
                "Interroge chaque source sur les structures du périmètre.",
                [group(phase("harvest"), "harvest")],
                doc="02-harvest.md#moissonnage-par-affiliation-harvest",
            ),
            step(
                "s1-2",
                "Recherche par personne",
                "Interroge les sources sur les identifiants ORCID, idHAL et IdRef des personnes du référentiel RH.",
                [group(phase("harvest_by_person"), "harvest_by_person")],
                doc="02-harvest.md#moissonnage-par-personne-harvest_by_person",
            ),
            step(
                "s1-3",
                "Recherche croisée",
                "Cherche dans chaque source les documents trouvés dans une autre, par hal-id, NNT, numéro de brevet ou DOI.",
                [group(phase("fetch_missing"), "fetch_missing")],
                doc="02-harvest.md#documents-absents-dune-source-fetch_missing",
            ),
            step(
                "s1-4",
                "Mise à jour",
                "Cherche de nouveau les documents non revus depuis un délai, repère les documents disparus et complète les listes d'auteurs tronquées.",
                [
                    group(phase("fetch_stale"), "fetch_stale"),
                    group(phase("fetch_truncated"), "fetch_truncated"),
                ],
                doc="02-harvest.md#documents-périmés-et-disparus-fetch_stale",
            ),
        ],
    },
    {
        "id": "n2",
        "num": "2",
        "title": "Normalisation",
        "role": "Convertit chaque document brut (JSON) en lignes SQL : enregistrement source, contributions sources, adresses.",
        "doc": "03-normalize.md",
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
        "role": "Relie les contributions sources aux structures, et décide lesquelles entrent dans le périmètre.",
        "doc": "04-affiliations.md#affiliations-affiliations",
        "steps": [
            step(
                "s3-1",
                "Reconnaissance des structures",
                "Cherche les noms des structures dans les adresses et dans les laboratoires partenaires des thèses.",
                [group(phase("affiliations", exclude=("decide_source_contribution_perimeter",)))],
            ),
            step(
                "s3-2",
                "Décision du périmètre",
                "Fait entrer une contribution source dans le périmètre quand elle atteint une structure du périmètre, ou porte l'identifiant d'une personne du référentiel RH.",
                [group(phase("affiliations", only=("decide_source_contribution_perimeter",)))],
            ),
        ],
    },
    {
        "id": "n4",
        "num": "4",
        "title": "Métadonnées",
        "role": "Corrige les métadonnées des enregistrements sources avant la réconciliation et la consolidation.",
        "doc": "06-metadata-correction.md",
        "steps": [
            step(
                "s4-1",
                "Correction des enregistrements",
                "Corrige le type de document, et retire les identifiants des dépôts HAL introuvables.",
                [group(phase("metadata_correction", only=("correct_source_records",)))],
            ),
            step(
                "s4-2",
                "Nettoyage des DOI",
                "Relie le DOI d'une forme secondaire à celui de l'œuvre, et retire les DOI partagés par des œuvres distinctes ou inconnus de doi.org.",
                [group(phase("metadata_correction", only=("doi_targets", "remove_identifiers")))],
            ),
            step(
                "s4-3",
                "Admission à la réconciliation",
                "Écarte de la réconciliation les paratextes, les doublons retirés par l'éditeur, les formes secondaires et les enregistrements OpenAlex ou ScanR sans clé.",
                [group(phase("metadata_correction", only=("decide_matchability",)))],
            ),
        ],
    },
    {
        "id": "n5",
        "num": "5",
        "title": "Publications",
        "role": "Regroupe les enregistrements sources d'un même document en une publication, et calcule ses métadonnées.",
        "doc": "07-publications.md",
        "steps": [
            step(
                "s5-1",
                "Réconciliation",
                "Regroupe les enregistrements sources d'un même document, reconnu par DOI, NNT, hal-id, ou type, titre et année.",
                [group(phase("publications", only=("reconcile",)))],
                doc="07-publications.md#reconnaître-la-même-publication",
            ),
            step(
                "s5-2",
                "Consolidation",
                "Calcule les métadonnées de chaque publication à partir de ses enregistrements sources : DOI, date, éditeur, pays…",
                [group(phase("publications", only=("consolidate_publications",)))],
                doc="07-publications.md#recalcul-des-métadonnées",
            ),
        ],
    },
    {
        "id": "n6",
        "num": "6",
        "title": "Personnes",
        "role": "Attribue chaque contribution à une personne du référentiel.",
        "doc": "09-persons.md",
        "steps": [
            step(
                "s6-1",
                "Alignement des auteurs",
                "Aligne les listes d'auteurs des enregistrements sources d'une même publication : chaque auteur devient une contribution.",
                [group(phase("author_grouping"))],
                doc="08-author-grouping.md",
            ),
            step(
                "s6-2",
                "Attribution",
                "Rattache chaque contribution à une personne : par épinglage manuel, par identifiant (ORCID, compte HAL, IdRef), puis par forme de nom. Le contexte de la publication départage les homonymes : coauteurs, laboratoires, revue, années. Une contribution du périmètre au nom inconnu crée une personne.",
                [group(phase("persons"))],
                doc="09-persons.md#rattacher-une-contribution-à-une-personne",
            ),
            step(
                "s6-3",
                "Attributions suspectes",
                "Repère les publications d'une personne qui s'écartent du reste de sa production ou ressemblent à des publications rejetées, et les signale pour vérification.",
                [group(phase("suspect_attributions"))],
                doc="09-persons.md#attributions-suspectes-suspect_attributions",
            ),
        ],
    },
    {
        "id": "nF",
        "num": None,
        "title": "Finalisation",
        "role": "Purge les publications et les référentiels vides, puis recalcule les données dérivées et les compteurs.",
        "doc": "10-finalize.md",
        "technical": True,
        "steps": [
            step(
                "sF-1",
                "Purges",
                "Supprime les publications sans enregistrement source ou sans personne, puis les monographies, revues et éditeurs devenus vides.",
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
                "Décide le périmètre des publications, les relie à leurs structures et donne à chaque revue son éditeur.",
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
                "Recompte les publications des adresses, revues et éditeurs, et l'usage des sujets.",
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
        "text": "Dresse la liste des structures de chaque périmètre.",
        "groups": [group(["perimeter_structures"])],
        "feeds": ["Recherche par affiliation", "Décision du périmètre"],
    },
    {
        "id": "a-str",
        "kind": "in",
        "title": "Référentiels de structures",
        "text": "Met à jour les organisations ROR et les structures HAL.",
        "doc": "04-affiliations.md#référentiels-ror-et-hal-structures",
        "groups": [group(phase("structures"), "structures")],
        "feeds": ["Décision du périmètre", "Pays"],
    },
    {
        "id": "a-doi",
        "kind": "in",
        "title": "Résolution des DOI",
        "text": "Demande à doi.org l'agence de chaque préfixe, l'existence et l'URL de chaque DOI.",
        "doc": "05-publishing.md#référentiel-des-doi-dois",
        "groups": [group(phase("dois"), "dois")],
        "feeds": ["Éditeurs", "Nettoyage des DOI"],
    },
    {
        "id": "a-edi",
        "kind": "in",
        "title": "Référentiels éditoriaux",
        "text": "Rattache chaque enregistrement source à son éditeur, sa revue et sa monographie.",
        "doc": "05-publishing.md#référentiels-de-lédition-publishing",
        "steps": [
            step(
                "e-pub",
                "Éditeurs",
                "Trouve l'éditeur titulaire de chaque préfixe DOI, puis rattache chaque enregistrement source à son éditeur.",
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
                doc="05-publishing.md#éditeurs",
            ),
            step(
                "e-ser",
                "Revues",
                None,
                steps=[
                    step(
                        "e-ser-1",
                        "Rattachement",
                        "Rattache chaque enregistrement source à sa revue, par ISSN-L, identifiant OpenAlex ou titre.",
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
                        "Type chaque revue (revue ou actes), et note sa fiche DOAJ et son modèle open access.",
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
                        "Retrouve la revue manquante d'un enregistrement source par l'espace de noms de son DOI.",
                        [
                            group(
                                phase(
                                    "publishing",
                                    only=("learn_serial_doi_namespaces", "serial_by_doi"),
                                )
                            )
                        ],
                        doc="05-publishing.md#espaces-de-noms-doi",
                    ),
                ],
                doc="05-publishing.md#publications-en-série",
            ),
            step(
                "e-mon",
                "Monographies",
                "Rattache chaque volume à sa monographie et à sa collection, et distingue les volumes d'actes.",
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
                doc="05-publishing.md#monographies",
            ),
        ],
        "feeds": ["Correction des enregistrements"],
    },
    {
        "id": "a-pay",
        "kind": "in",
        "title": "Pays",
        "text": "Détecte les pays des adresses, et les reporte sur les enregistrements sources.",
        "doc": "04-affiliations.md#pays-countries",
        "groups": [group(phase("countries"), "countries")],
        "feeds": ["Consolidation"],
    },
    {
        "id": "a-rel",
        "kind": "out",
        "title": "Relations",
        "text": "Relie les publications à leurs versions, errata et avis de rétractation.",
        "doc": "11-enrichissements.md#relations-entre-publications-relations",
        "groups": [group(phase("relations"), "relations")],
        "feeds": [],
    },
    {
        "id": "a-oa",
        "kind": "out",
        "title": "Open access",
        "text": "Demande à Unpaywall le statut open access du DOI de chaque publication, puis calcule le statut de la publication.",
        "doc": "11-enrichissements.md#statut-open-access-open_access",
        "groups": [group(phase("open_access"), "open_access")],
        "feeds": [],
    },
    {
        "id": "a-sub",
        "kind": "out",
        "title": "Sujets",
        "text": "Reporte sur chaque publication les sujets donnés par les sources.",
        "doc": "11-enrichissements.md#sujets-subjects",
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


def _all_steps(steps: list[Step]) -> list[Step]:
    """Renvoie les étapes et toutes leurs sous-étapes."""
    return [x for s in steps for x in [s, *_all_steps(s["steps"])]]


def placed_tasks() -> list[str]:
    """Renvoie les tâches rangées dans les blocs et les affluents, dans l'ordre de la page."""
    groups = [g for n in NODES for s in _leaves(n["steps"]) for g in s["groups"]]
    for a in AFFLUENTS:
        groups += a.get("groups", []) + [
            g for s in _leaves(a.get("steps", [])) for g in s["groups"]
        ]
    return [t for g in groups for t in g["tasks"]]


def doc_links() -> dict[str, str]:
    """Renvoie le lien `doc` de chaque bloc, étape et affluent qui en a un, par identifiant."""
    links: dict[str, str | None] = {}
    for n in NODES:
        links[n["id"]] = n["doc"]
        links.update({s["id"]: s["doc"] for s in _all_steps(n["steps"])})
    for a in AFFLUENTS:
        links[a["id"]] = a.get("doc")
        links.update({s["id"]: s["doc"] for s in _all_steps(a.get("steps", []))})
    return {k: v for k, v in links.items() if v}


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
