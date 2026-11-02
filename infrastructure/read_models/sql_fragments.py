"""Fragments SQL partagés entre read models, rendus depuis les alias de la requête hôte."""

from domain.persons.identifiers import AttributionStatus


def contributor_display_name(source_contribution: str = "sc") -> str:
    """Renvoie le nom de la contribution source aliasée `source_contribution`, tel que donné par la source : chaîne brute, ou « Prénom Nom » (`ContributorName.display`)."""
    return (
        f"coalesce({source_contribution}.raw_author_name,"
        f" concat_ws(' ', {source_contribution}.raw_first_name, {source_contribution}.raw_last_name))"
    )


def source_contribution_structure_ids(source_contribution: str = "sc") -> str:
    """Renvoie la sous-requête (`structure_id`) des structures atteintes par la contribution source aliasée `source_contribution`, chacune une fois.

    La vue matérialisée `source_contribution_structures` contient une ligne par indice (adresse, ROR, structure HAL) : une structure atteinte par deux indices y figure deux fois.
    """
    return (
        "SELECT DISTINCT scs.structure_id FROM source_contribution_structures scs"
        f" WHERE scs.source_contribution_id = {source_contribution}.id"
    )


def contribution_has_source(source: str, group: str = "a") -> str:
    """Renvoie la condition : la contribution aliasée `group` a une contribution source alignée dont l'enregistrement source est de `source`."""
    return (
        "EXISTS (SELECT 1 FROM aligned_source_contributions m_src"
        " JOIN source_records sr_src ON sr_src.id = m_src.source_record_id"
        f" WHERE m_src.contribution_id = {group}.id AND sr_src.source = '{source}')"
    )


def name_form_holder(form: str, person: str) -> str:
    """Renvoie la condition : la personne aliasée `person` détient la forme de nom aliasée `form` (forme non rejetée, personne non exclue)."""
    return f"{form}.status <> '{AttributionStatus.REJECTED.value}' AND {person}.exclusion IS NULL"


def other_name_form_holders(name_form: str, person_id: str) -> str:
    """Renvoie la sous-requête (`person_id`) des autres personnes détenant la forme de nom au sens de `name_form_holder`, `person_id` exclu.

    `name_form` et `person_id` sont des expressions SQL : paramètres (`:nf`) ou colonnes de la requête hôte.
    """
    return (
        "SELECT holder.person_id FROM person_name_forms holder"
        " JOIN persons holder_person ON holder_person.id = holder.person_id"
        f" WHERE holder.name_form = {name_form} AND holder.person_id <> {person_id}"
        f" AND {name_form_holder('holder', 'holder_person')}"
    )


def current_hr_period(period: str = "hp") -> str:
    """Renvoie la condition vraie quand la période de présence aliasée `period` couvre la date du jour. Une date absente est une borne ouverte."""
    return (
        f"({period}.start_date IS NULL OR {period}.start_date <= current_date)"
        f" AND ({period}.end_date IS NULL OR {period}.end_date >= current_date)"
    )


def current_unit(person: str = "p") -> str:
    """Renvoie la sous-requête du libellé de l'unité actuelle de la personne aliasée `person`, qui sert à départager des homonymes : structure reconnue d'abord, à défaut libellé de l'unité."""
    return f"""(
        SELECT coalesce(cu_s.acronym, cu_s.name, cu_hp.unit_label)
        FROM hr_periods cu_hp
        LEFT JOIN structures cu_s ON cu_s.id = cu_hp.structure_id
        WHERE cu_hp.person_id = {person}.id AND {current_hr_period("cu_hp")}
        ORDER BY cu_hp.structure_id IS NULL, cu_hp.start_date DESC NULLS LAST, cu_hp.unit_label
        LIMIT 1
    )"""


def current_laboratory_label(person: str = "p") -> str:
    """Renvoie la sous-requête du premier libellé, dans l'ordre alphabétique, des structures des périodes actuelles de la personne aliasée `person`. Sert au tri."""
    return f"""(
        SELECT min(coalesce(cl_s.acronym, cl_s.name))
        FROM hr_periods cl_hp
        JOIN structures cl_s ON cl_s.id = cl_hp.structure_id
        WHERE cl_hp.person_id = {person}.id AND {current_hr_period("cl_hp")}
    )"""
