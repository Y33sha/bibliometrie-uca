"""Ordre des phases du pipeline.

Source de vérité unique de l'ordre d'exécution, consommée par l'orchestrateur (`run_pipeline.py`) et par la lecture d'observabilité (API, trame du ruban de l'interface). L'ordre de déclaration est l'ordre d'exécution. Module pur, sans I/O.
"""

from __future__ import annotations

PHASE_ORDER: tuple[str, ...] = (
    "extract",
    "resolve_ra",
    "cross_imports",
    "refresh_stale",
    "refetch_truncated",
    "normalize",
    "affiliations",
    "publishers_journals",
    "metadata_correction",
    "publications",
    "relations",
    "persons",
    "authorships",
    "countries",
    "subjects",
    "oa_status",
)

if len(set(PHASE_ORDER)) != len(PHASE_ORDER):
    raise ValueError("Noms de phase dupliqués dans PHASE_ORDER")
