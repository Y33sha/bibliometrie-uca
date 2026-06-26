"""Graphe des phases du pipeline.

Source de vérité unique de la structure du pipeline, consommée par la capture d'observabilité (orchestrateur) et par sa lecture (API, interface). Pour chaque phase : les tables qu'elle consomme en entrée et celles qu'elle produit en sortie. Module pur, sans I/O.

Les tables consommées définissent l'observable d'entrée (volume capturé au début de la phase), les tables produites l'observable de sortie (volume capturé à la fin) ; leur comparaison avant / après donne le mouvement de volume de la phase. Une phase qui enrichit une table en place (même volume avant / après) ne s'observe pas par ce mouvement : elle remonte ses propres indicateurs sur-mesure.

L'ordre de déclaration est l'ordre d'exécution du pipeline ; la validation à l'import vérifie l'unicité des noms.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseNode:
    """Une phase du pipeline et ses tables. `consumes` / `produces` : tables métier lues en entrée / écrites en sortie ; une table figure dans les deux quand la phase enrichit en place."""

    name: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]


PIPELINE_GRAPH: tuple[PhaseNode, ...] = (
    PhaseNode("extract", (), ("staging",)),
    PhaseNode("resolve_ra", ("doi_prefixes",), ("doi_prefixes",)),
    PhaseNode("cross_imports", ("staging",), ("staging",)),
    PhaseNode("refresh_stale", ("staging",), ("staging",)),
    PhaseNode("refetch_truncated", ("staging",), ("staging",)),
    PhaseNode(
        "normalize",
        ("staging",),
        ("source_publications", "source_authorships", "addresses"),
    ),
    PhaseNode(
        "affiliations",
        ("source_authorships",),
        ("source_authorships", "addresses"),
    ),
    PhaseNode(
        "publishers_journals",
        ("source_publications", "doi_prefixes"),
        ("publishers", "journals", "doi_prefixes"),
    ),
    PhaseNode(
        "metadata_correction",
        ("source_publications",),
        ("source_publications",),
    ),
    PhaseNode("publications", ("source_publications",), ("publications",)),
    PhaseNode(
        "relations",
        ("source_publications", "publications"),
        ("publication_relations",),
    ),
    PhaseNode(
        "persons",
        ("source_authorships",),
        ("persons", "person_identifiers", "person_name_forms"),
    ),
    PhaseNode("authorships", ("source_authorships",), ("authorships",)),
    PhaseNode("countries", ("addresses",), ("addresses",)),
    PhaseNode(
        "subjects",
        ("source_publications",),
        ("subjects", "publication_subjects"),
    ),
    PhaseNode("oa_status", ("publications",), ("publications",)),
)

PHASE_ORDER: tuple[str, ...] = tuple(phase.name for phase in PIPELINE_GRAPH)

_BY_NAME: dict[str, PhaseNode] = {phase.name: phase for phase in PIPELINE_GRAPH}


def node(name: str) -> PhaseNode:
    """Renvoie la phase nommée, ou lève `KeyError` si elle n'existe pas."""
    return _BY_NAME[name]


def _validate() -> None:
    """Vérifie que les noms de phase sont uniques."""
    if len(_BY_NAME) != len(PIPELINE_GRAPH):
        raise ValueError("Noms de phase dupliqués dans PIPELINE_GRAPH")


_validate()
