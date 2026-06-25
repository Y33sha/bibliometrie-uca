"""Graphe des phases du pipeline.

Source de vérité unique de la structure du pipeline, consommée par la capture
d'observabilité (orchestrateur) et par sa lecture (API, interface). Pour chaque
phase : ses phases amont directes, les tables qu'elle consomme en entrée et
celles qu'elle produit en sortie. Module pur, sans I/O.

Les tables consommées définissent l'observable d'entrée (volume capturé au début
de la phase), les tables produites l'observable de sortie (volume capturé à la
fin) ; leur rapport donne le rendement de la phase. Les phases d'extraction et de
récupération (`extract`, `resolve_ra`, `cross_imports`, `refresh_stale`,
`refetch_truncated`) ont une entrée essentiellement externe (API sources) : leur
rendement local est secondaire, c'est l'absolu produit qui parle.

L'ordre de déclaration est topologique : toute phase amont précède celles qui en
dépendent. La validation à l'import le garantit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseNode:
    """Une phase du pipeline et ses dépendances de données.

    `upstream` : phases dont la sortie est consommée directement (arêtes du DAG).
    `consumes` / `produces` : tables métier lues en entrée / écrites en sortie.
    Une table figure dans les deux quand la phase enrichit en place.
    """

    name: str
    upstream: tuple[str, ...]
    consumes: tuple[str, ...]
    produces: tuple[str, ...]


PIPELINE_GRAPH: tuple[PhaseNode, ...] = (
    PhaseNode("extract", (), (), ("staging",)),
    PhaseNode("resolve_ra", ("extract",), ("staging",), ("doi_prefixes",)),
    PhaseNode("cross_imports", ("extract", "resolve_ra"), ("staging",), ("staging",)),
    PhaseNode("refresh_stale", ("cross_imports",), ("staging",), ("staging",)),
    PhaseNode("refetch_truncated", ("refresh_stale",), ("staging",), ("staging",)),
    PhaseNode(
        "normalize",
        ("refetch_truncated",),
        ("staging",),
        ("source_publications", "source_authorships", "addresses"),
    ),
    PhaseNode(
        "affiliations",
        ("normalize",),
        ("source_authorships",),
        ("source_authorships", "addresses"),
    ),
    PhaseNode(
        "publishers_journals",
        ("normalize", "resolve_ra"),
        ("source_publications", "doi_prefixes"),
        ("publishers", "journals", "doi_prefixes"),
    ),
    PhaseNode(
        "metadata_correction",
        ("normalize",),
        ("source_publications",),
        ("source_publications",),
    ),
    PhaseNode(
        "publications",
        ("metadata_correction",),
        ("source_publications",),
        ("publications",),
    ),
    PhaseNode(
        "relations",
        ("normalize", "publications"),
        ("source_publications", "publications"),
        ("publication_relations",),
    ),
    PhaseNode(
        "persons",
        ("affiliations",),
        ("source_authorships",),
        ("persons", "person_identifiers", "person_name_forms"),
    ),
    PhaseNode(
        "authorships",
        ("publications", "persons"),
        ("source_authorships",),
        ("authorships",),
    ),
    PhaseNode(
        "countries",
        ("affiliations", "publications"),
        ("addresses",),
        ("addresses",),
    ),
    PhaseNode(
        "subjects",
        ("publications",),
        ("source_publications",),
        ("subjects", "publication_subjects"),
    ),
    PhaseNode("oa_status", ("publications",), ("publications",), ("publications",)),
)

PHASE_ORDER: tuple[str, ...] = tuple(phase.name for phase in PIPELINE_GRAPH)

_BY_NAME: dict[str, PhaseNode] = {phase.name: phase for phase in PIPELINE_GRAPH}


def node(name: str) -> PhaseNode:
    """Renvoie la phase nommée, ou lève `KeyError` si elle n'existe pas."""
    return _BY_NAME[name]


def _validate() -> None:
    """Vérifie que le graphe est un DAG en ordre topologique : chaque phase amont
    existe et est déclarée avant la phase qui en dépend."""
    seen: set[str] = set()
    for phase in PIPELINE_GRAPH:
        for parent in phase.upstream:
            if parent not in _BY_NAME:
                raise ValueError(f"Phase {phase.name!r} : amont inconnu {parent!r}")
            if parent not in seen:
                raise ValueError(
                    f"Phase {phase.name!r} : amont {parent!r} déclaré après elle "
                    "(ordre non topologique)"
                )
        seen.add(phase.name)


_validate()
