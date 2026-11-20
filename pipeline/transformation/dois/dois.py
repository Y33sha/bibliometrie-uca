"""Phase `dois` : référentiel des DOI connus (`doi_prefixes`, `dois`).

Les tâches s'enchaînent dans cet ordre :

1. `resolve_prefixes` demande à doi.org l'agence de chaque préfixe nouveau (`registration_agencies`).
2. `resolve_dois` demande à l'API des handles de doi.org l'existence et l'URL de résolution de chaque DOI connu (`lookups`). Les publications d'un DOI dont la réponse change entrent dans la file de consolidation.
"""

from pipeline.graph import Block, Phase
from pipeline.transformation.dois import lookups, registration_agencies

PHASE = Phase(
    "dois",
    "Référentiel des DOI",
    (*registration_agencies.TASKS, lookups.RESOLVE_DOIS),
    Block.SOURCE_RECORDS,
    assemble=lookups.assemble,
)
