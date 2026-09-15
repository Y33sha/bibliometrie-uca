"""Fragments SQL partagés entre adaptateurs.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), des expressions rendues depuis les alias de la requête hôte (identifiants d'une signature), et des expressions SQL figées réutilisées par plusieurs adaptateurs.
"""

from domain.persons.identifiers import AttributionStatus


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def identifier_neutralized(
    id_type: str, signature: str = "sa", *, reason: str | None = None
) -> str:
    """Condition vraie quand la signature aliasée `signature` neutralise l'identifiant `id_type`, pour le motif `reason` s'il est donné.

    `id_type` est une expression SQL : littéral (`'orcid'`), paramètre (`:id_type`) ou colonne.
    """
    if reason is None:
        return f"coalesce({signature}.neutralized_identifiers ? {id_type}, false)"
    return f"coalesce({signature}.neutralized_identifiers ->> {id_type} = '{reason}', false)"


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


def other_name_form_holders(name_form: str, person_id: str) -> str:
    """Sous-requête (`person_id`) des autres personnes qui portent la forme de nom : forme non rejetée, personne non rejetée, `person_id` exclu.

    `name_form` et `person_id` sont des expressions SQL : paramètres (`:nf`) ou colonnes de la requête hôte.
    """
    return (
        "SELECT holder.person_id FROM person_name_forms holder"
        " JOIN persons holder_person ON holder_person.id = holder.person_id"
        f" WHERE holder.name_form = {name_form} AND holder.person_id <> {person_id}"
        f" AND holder.status <> '{AttributionStatus.REJECTED.value}'"
        " AND NOT holder_person.rejected"
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
