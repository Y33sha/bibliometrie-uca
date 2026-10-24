"""Fragments SQL partagés entre read models, rendus depuis les alias de la requête hôte."""

from domain.persons.identifiers import AttributionStatus


def contributor_display_name(source_contribution: str = "sc") -> str:
    """Nom de la contribution source aliasée `source_contribution` tel que la source le donne : chaîne brute, ou « Prénom Nom » (`ContributorName.display`)."""
    return (
        f"coalesce({source_contribution}.raw_author_name,"
        f" concat_ws(' ', {source_contribution}.raw_first_name, {source_contribution}.raw_last_name))"
    )


def source_contribution_structure_ids(source_contribution: str = "sc") -> str:
    """Sous-requête (`structure_id`) des structures atteintes par la contribution source aliasée `source_contribution`, chacune une fois. La matview `source_contribution_structures` contient une ligne par indice (adresse, ROR, structure HAL) : une structure atteinte par deux indices y figure deux fois."""
    return (
        "SELECT DISTINCT scs.structure_id FROM source_contribution_structures scs"
        f" WHERE scs.source_contribution_id = {source_contribution}.id"
    )


def contribution_has_source(source: str, group: str = "a") -> str:
    """Condition vraie quand le groupe aliasé `group` a un membre dont l'enregistrement source est de `source`."""
    return (
        "EXISTS (SELECT 1 FROM source_contribution_group_members m_src"
        " JOIN source_records sr_src ON sr_src.id = m_src.source_record_id"
        f" WHERE m_src.group_id = {group}.id AND sr_src.source = '{source}')"
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
