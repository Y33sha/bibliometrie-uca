"""Lecture des payloads theses.fr par la normalisation : conventions des champs de theses.fr.

Les payloads sont les objets JSON bruts de l'API, sans schéma typé.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import THESES_FIELD_ROLES, ContributionRole, merge_roles
from domain.publications.metadata import OaStatus
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.source_contributions import contributor_identifiers

# Cas de diffusion STAR avec une version de la thèse destinée à Internet. Les cas 5 et 6 réservent la thèse à l'intranet de l'établissement.
_INTERNET_CASES = frozenset({"cas1", "cas2", "cas3", "cas4"})


def awaits_diffusion(thesis: Mapping[str, JsonValue]) -> bool:
    """Vrai pour une thèse inaccessible destinée à Internet (cas 1 à 4) : elle attend la fin d'un embargo ou d'une confidentialité."""
    return (
        as_str(thesis.get("accessible")) != "oui" and as_str(thesis.get("cas")) in _INTERNET_CASES
    )


def intranet_only(thesis: Mapping[str, JsonValue]) -> bool:
    """Vrai pour une thèse réservée à l'intranet de son établissement (cas 5 et 6)."""
    return as_str(thesis.get("cas")) in ("cas5", "cas6")


def thesis_oa_status(thesis: Mapping[str, JsonValue]) -> OaStatus:
    """Renvoie le statut open access d'une thèse, d'après sa diffusion (`accessible`, `cas`).

    Une thèse accessible est `green`. Une thèse inaccessible destinée à Internet (cas 1 à 4) attend la fin d'un embargo ou d'une confidentialité : elle est `embargoed`. Les autres sont `closed` : intranet seulement, ou thèse en cours sans fichier.
    """
    if as_str(thesis.get("accessible")) == "oui":
        return OaStatus.GREEN
    if as_str(thesis.get("cas")) in _INTERNET_CASES:
        return OaStatus.EMBARGOED
    return OaStatus.CLOSED


def derive_theses_doc_type(defense_date: str | None) -> str:
    """Renvoie le type d'une thèse theses.fr : `thesis` avec une date de soutenance, `ongoing_thesis` sans.

    La date de soutenance est le seul signal fiable pour distinguer thèse soutenue et thèse en préparation.
    """
    return "thesis" if defense_date else "ongoing_thesis"


@dataclass(frozen=True)
class ThesisContribution:
    """Une personne d'une thèse, avec ses rôles fusionnés (`aggregate_thesis_persons`)."""

    person: Mapping[str, JsonValue]
    """Objet brut de l'API."""
    roles: list[ContributionRole]
    name: ContributorName
    author_position: int | None
    identifiers: dict[str, JsonValue] | None
    is_author: bool


def aggregate_thesis_persons(thesis: Mapping[str, JsonValue]) -> list[ThesisContribution]:
    """Renvoie les personnes d'une thèse, une fois chacune, avec leurs rôles fusionnés.

    Les personnes viennent des champs `auteurs`, `directeurs`, `rapporteurs`, `membresJury` et `presidentJury` (`THESES_FIELD_ROLES`). Une personne présente dans plusieurs champs est identifiée par son PPN, à défaut par son nom et son prénom ; ses rôles se fusionnent (`merge_roles`). C'est presque toujours le président du jury qui est aussi rapporteur.

    Seuls les auteurs ont une position, dans l'ordre de `auteurs`.
    """
    # Une personne apparaissant dans plusieurs champs est retenue une fois, ses rôles cumulés.
    persons_by_key: dict[str, Mapping[str, JsonValue]] = {}
    roles_by_key: dict[str, list[ContributionRole]] = {}

    for field, roles in THESES_FIELD_ROLES.items():
        if field == "presidentJury":
            president = as_mapping(thesis.get(field))
            persons = [president] if as_str(president.get("nom")) else []
        else:
            persons = [as_mapping(p) for p in as_sequence(thesis.get(field))]

        for person in persons:
            last_name = as_str(person.get("nom"))
            if not last_name:
                continue
            ppn = as_str(person.get("ppn"))
            key = ppn if ppn else f"name:{last_name}:{as_str(person.get('prenom')) or ''}"
            persons_by_key.setdefault(key, person)
            roles_by_key.setdefault(key, []).extend(roles)

    out: list[ThesisContribution] = []
    position = 0
    for key, person in persons_by_key.items():
        name = ContributorName.from_parts(as_str(person.get("nom")), as_str(person.get("prenom")))
        if name is None:
            continue
        merged = merge_roles([roles_by_key[key]])
        is_author = ContributionRole.AUTHOR in merged
        ppn = as_str(person.get("ppn"))
        identifiers = contributor_identifiers(idref=ppn)

        out.append(
            ThesisContribution(
                person=person,
                roles=merged,
                name=name,
                author_position=position if is_author else None,
                identifiers=identifiers,
                is_author=is_author,
            )
        )
        if is_author:
            position += 1
    return out
