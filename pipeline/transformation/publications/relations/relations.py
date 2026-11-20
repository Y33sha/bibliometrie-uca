"""Phase `relations` : relations entre publications (`rebuild`), relations avec les errata et les avis (`notices`), puis indicateur « Rétracté » des publications (`retractions`)."""

from pipeline.graph import Block, Phase
from pipeline.transformation.publications.relations import notices, rebuild, retractions

PHASE = Phase(
    "relations",
    "Relations entre publications, indicateur « Rétracté »",
    (*rebuild.TASKS, *notices.TASKS, *retractions.TASKS),
    Block.ENTITIES,
)
