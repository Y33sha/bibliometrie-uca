"""Fragments SQL partagés entre l'API et le pipeline.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), des expressions rendues depuis les alias de la requête hôte (identifiants d'une signature), et des expressions SQL figées.
"""


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
    """Valeur de l'identifiant `id_type` dans l'identité d'une signature, NULL quand la signature le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, signature)} THEN NULL"
        f" ELSE {identity}.person_identifiers ->> {id_type} END"
    )


# Paires (publication, personne) rejetées : une publication est rejetée pour une personne dès qu'une de ses notices l'est.
REJECTED_PAIRS = (
    "SELECT sp_rej.publication_id, rej.person_id FROM rejected_authorships rej"
    " JOIN source_publications sp_rej ON sp_rej.id = rej.source_publication_id"
)


def publication_rejected_for(publication_id: str, person_id: str) -> str:
    """Condition vraie quand la publication `publication_id` est rejetée pour la personne `person_id` (expressions SQL) : une de ses notices l'est."""
    return (
        "EXISTS (SELECT 1 FROM rejected_authorships rej"
        " JOIN source_publications sp_rej ON sp_rej.id = rej.source_publication_id"
        f" WHERE sp_rej.publication_id = {publication_id} AND rej.person_id = {person_id})"
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


def active_issns(journal: str) -> str:
    """Tableau des ISSN actifs de la revue `journal` (expression SQL), dans l'ordre d'enregistrement ; tableau vide sans ISSN."""
    return f"""coalesce((
        SELECT array_agg(i.issn ORDER BY i.id) FROM journal_issns i
        WHERE i.journal_id = {journal} AND i.status = 'active'
    ), ARRAY[]::text[])"""


def has_active_issn(journal: str) -> str:
    """Condition vraie quand la revue `journal` a un ISSN actif."""
    return f"EXISTS (SELECT 1 FROM journal_issns i WHERE i.journal_id = {journal} AND i.status = 'active')"
