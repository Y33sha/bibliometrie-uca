"""Lecture des enregistrements sources theses.fr par la normalisation.

Interprétation des champs propres au schéma theses.fr — prédicats et fonctions de lecture qui encapsulent la connaissance de la sémantique theses.fr.

Les `Mapping[str, JsonValue]` ici sont des payloads JSON bruts de l'API theses.fr (frontière dynamique avec une source externe, schéma non typé). Le champ `person` du dataclass `ThesisContribution` transmet tel quel le sous-objet personne au caller.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import THESES_FIELD_ROLES, ContributionRole, merge_roles
from domain.publications.metadata import OaStatus
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.source_contributions import contributor_identifiers

# Cas de diffusion STAR où une version de la thèse est destinée à Internet. Les cas 5 et 6 réservent la thèse à l'intranet de l'établissement.
_INTERNET_CASES = frozenset({"cas1", "cas2", "cas3", "cas4"})


def thesis_oa_status(thesis: Mapping[str, JsonValue]) -> OaStatus:
    """Statut open access d'une thèse, d'après sa diffusion (`accessible`, `cas`).

    Une thèse accessible est `green`. Une thèse inaccessible destinée à Internet (cas 1 à 4) attend la fin d'un embargo ou d'une confidentialité : elle est `embargoed`. Les autres sont `closed` : intranet seulement, ou thèse en cours sans fichier.
    """
    if as_str(thesis.get("accessible")) == "oui":
        return OaStatus.GREEN
    if as_str(thesis.get("cas")) in _INTERNET_CASES:
        return OaStatus.EMBARGOED
    return OaStatus.CLOSED


def derive_theses_doc_type(defense_date: str | None) -> str:
    """Mapping date_soutenance → doc_type canonique pour theses.fr.

    theses.fr distribue à la fois les thèses soutenues et les thèses en préparation. La date de soutenance est le seul signal fiable pour distinguer les deux états :
      - dateSoutenance présent → 'thesis' (soutenue)
      - dateSoutenance absent → 'ongoing_thesis' (en cours)
    """
    return "thesis" if defense_date else "ongoing_thesis"


@dataclass(frozen=True)
class ThesisContribution:
    """Une personne d'une thèse, avec ses rôles fusionnés.

    Produite par `aggregate_thesis_persons` à partir du dict `thesis` de l'API theses.fr. `person` est le dict brut, transmis tel quel au caller pour les effets (extraction d'identifiants, écriture sur `source_contributions`).
    """

    person: Mapping[str, JsonValue]
    roles: list[ContributionRole]
    name: ContributorName
    author_position: int | None
    identifiers: dict[str, JsonValue] | None
    is_author: bool


def aggregate_thesis_persons(thesis: Mapping[str, JsonValue]) -> list[ThesisContribution]:
    """Agrège les personnes d'une thèse depuis `thesis` (API theses.fr).

    Itère sur les champs `auteurs`, `directeurs`, `rapporteurs`, `membresJury`, `presidentJury` (cf. `THESES_FIELD_ROLES`). Une personne qui apparaît dans plusieurs champs est dédupliquée (clé : PPN si présent, sinon `(nom, prenom)`) et ses rôles sont fusionnés via `merge_roles`.

    En pratique, le cas multi-rôles concerne presque exclusivement le président du jury qui est aussi rapporteur (~1 % des contributions theses au 2026-05-08).

    `author_position` est incrémenté seulement pour les personnes dont les rôles fusionnés contiennent `'author'` ; `None` pour les autres rôles (directeurs/rapporteurs/jury/président). Ordre des auteurs : celui de la liste `thesis["auteurs"]`.
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
