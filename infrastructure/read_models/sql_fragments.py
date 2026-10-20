"""Fragments SQL partagés entre read models, rendus depuis les alias de la requête hôte."""

from domain.persons.identifiers import AttributionStatus


def signature_display_name(signature: str = "sa") -> str:
    """Nom de la signature aliasée `signature` tel que la source le donne : chaîne brute, ou « Prénom Nom » (`SignatureName.display`)."""
    return (
        f"coalesce({signature}.raw_author_name,"
        f" concat_ws(' ', {signature}.raw_first_name, {signature}.raw_last_name))"
    )


def contribution_has_signature_from(source: str, contribution: str = "a") -> str:
    """Condition vraie quand la contribution aliasée `contribution` est attestée par une signature de `source` : même publication par sa notice, même personne."""
    return (
        "EXISTS (SELECT 1 FROM source_contributions sa_src"
        " JOIN source_records sp_src ON sp_src.id = sa_src.source_record_id"
        f" WHERE sp_src.publication_id = {contribution}.publication_id"
        f" AND sa_src.person_id = {contribution}.person_id AND sa_src.source = '{source}')"
    )


def name_form_holder(form: str, person: str) -> str:
    """Condition vraie quand la personne aliasée `person` détient la forme de nom aliasée `form` : forme non rejetée, personne non exclue."""
    return f"{form}.status <> '{AttributionStatus.REJECTED.value}' AND {person}.exclusion IS NULL"


def other_name_form_holders(name_form: str, person_id: str) -> str:
    """Sous-requête (`person_id`) des autres personnes qui détiennent la forme de nom au sens de `name_form_holder`, `person_id` exclu.

    `name_form` et `person_id` sont des expressions SQL : paramètres (`:nf`) ou colonnes de la requête hôte.
    """
    return (
        "SELECT holder.person_id FROM person_name_forms holder"
        " JOIN persons holder_person ON holder_person.id = holder.person_id"
        f" WHERE holder.name_form = {name_form} AND holder.person_id <> {person_id}"
        f" AND {name_form_holder('holder', 'holder_person')}"
    )
