"""Phase `embeddings` : vecteur de chaque publication, tiré de son titre et de son résumé (`encoding`)."""

from pipeline.graph import Block, Phase
from pipeline.transformation.publications.embeddings import encoding

PHASE = Phase(
    "embeddings",
    "Embeddings des publications : titre et résumé encodés en vecteurs",
    encoding.TASKS,
    Block.ENTITIES,
)
