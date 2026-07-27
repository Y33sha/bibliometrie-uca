"""Fragments SQL rendus depuis des tuples de valeurs (enums, ordres de priorité du domaine).

Les valeurs viennent de constantes du domaine (jamais d'entrée utilisateur) : l'interpolation directe dans le SQL est sûre.
"""


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"
