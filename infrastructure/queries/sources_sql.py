"""Rendu SQL des listes et ordres de priorité de sources.

Traduit les tuples du registre domaine (`domain.sources.registry`) en fragments SQL — contenu de clause `IN`, expression `CASE` de priorité — pour les query services et repositories. Les sources sont des constantes du registre (jamais une entrée utilisateur) : l'interpolation directe dans le SQL est sûre.
"""

from domain.sources.registry import AUTHOR_SOURCES


def _sources_in_sql(sources: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` à partir d'un tuple de sources : `('hal', 'openalex', …)`."""
    return "(" + ", ".join(f"'{s}'" for s in sources) + ")"


# Fragment `IN (...)` des sources à auteurs exploitables, prêt à interpoler dans un `sa.source IN {...}`.
AUTHOR_SOURCES_SQL = _sources_in_sql(AUTHOR_SOURCES)


def source_case_sql(priorities: tuple[str, ...], col: str = "sa.source") -> str:
    """Fragment SQL `CASE <col> WHEN 's1' THEN 1 ... END` à partir d'un tuple de sources, pour poser une priorité dans un `ORDER BY` ou un `array_agg(... ORDER BY ...)`."""
    whens = " ".join(f"WHEN '{s}' THEN {i + 1}" for i, s in enumerate(priorities))
    return f"CASE {col} {whens} END"
