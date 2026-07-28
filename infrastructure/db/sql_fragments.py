"""Fragments SQL partagés entre adaptateurs.

Deux formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), et des expressions SQL figées réutilisées par plusieurs adaptateurs.
"""


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


# Vrai dès qu'une signature de la paire (publication, personne) de `authorships` est
# elle-même in-perimeter. Suppose la table `authorships` aliasée `a` dans la requête hôte.
AUTHORSHIP_IN_PERIMETER_EXPR = """
    EXISTS (
        SELECT 1
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sd.publication_id = a.publication_id
          AND sa.person_id = a.person_id
          AND sa.in_perimeter = TRUE
    )
"""
