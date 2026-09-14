"""Fragments SQL partagés entre adaptateurs.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), des expressions rendues depuis les alias de la requête hôte (identifiants d'une signature), et des expressions SQL figées réutilisées par plusieurs adaptateurs.
"""


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def identifier_neutralized(id_type: str, signature: str = "sa") -> str:
    """Condition vraie quand la signature aliasée `signature` neutralise l'identifiant `id_type`.

    `id_type` est une expression SQL : littéral (`'orcid'`), paramètre (`:id_type`) ou colonne.
    """
    return f"coalesce({signature}.neutralized_identifiers ? {id_type}, false)"


def usable_identifier(id_type: str, *, signature: str = "sa", identity: str = "aik") -> str:
    """Valeur de l'identifiant `id_type` que porte l'identité d'une signature, NULL quand la signature le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, signature)} THEN NULL"
        f" ELSE {identity}.person_identifiers ->> {id_type} END"
    )


def usable_identifiers(*, signature: str = "sa", identity: str = "aik") -> str:
    """Identifiants de l'identité d'une signature, sans ceux que la signature neutralise (jsonb)."""
    return (
        f"({identity}.person_identifiers - ARRAY(SELECT jsonb_object_keys("
        f"coalesce({signature}.neutralized_identifiers, '{{}}'::jsonb))))"
    )


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
