"""Phase `dois` : référentiel des DOI connus (`doi_prefixes`, `dois`).

Les tâches s'enchaînent dans cet ordre :

1. `resolve_prefixes` demande à doi.org l'agence de chaque préfixe nouveau (`registration_agencies`).
2. `resolve_dois` demande à l'API des handles de doi.org l'existence et l'URL de résolution de chaque DOI connu (`lookups`).
3. `verify_unpaywall` demande à Unpaywall le statut open access de chaque DOI candidat au DOI d'une publication, hors DOI DataCite. Elle lit l'agence posée par la première tâche.

Les publications d'un DOI dont la réponse change entrent dans la file de consolidation.
"""

from pipeline.transformation.dois import lookups, registration_agencies

TASKS = (*registration_agencies.TASKS, *lookups.TASKS)

assemble = lookups.assemble
