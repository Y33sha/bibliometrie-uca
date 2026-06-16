"""Règles métier pures spécifiques à la source theses.fr.

Interprétation des champs propres au schéma theses.fr — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique theses.fr
pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API
theses.fr (frontière dynamique avec une source externe, schéma non
typé). Le champ `person` du dataclass ``ThesisAuthorship`` transmet
tel quel le sous-objet personne au caller (notamment pour extraire
les identifiants et le `raw_author_name` portés sur la `source_authorship`).
"""

from dataclasses import dataclass
from typing import Any

from domain.publications.authorship_roles import THESES_FIELD_ROLES, merge_roles


def derive_theses_doc_type(date_soutenance: str | None) -> str:
    """Mapping date_soutenance → doc_type canonique pour theses.fr.

    theses.fr distribue à la fois les thèses soutenues et les thèses
    en préparation. La date de soutenance est le seul signal fiable
    pour distinguer les deux états :
      - dateSoutenance présent → 'thesis' (soutenue)
      - dateSoutenance absent → 'ongoing_thesis' (en cours)
    """
    return "thesis" if date_soutenance else "ongoing_thesis"


@dataclass(frozen=True)
class ThesisAuthorship:
    """Une personne d'une thèse, avec ses rôles fusionnés.

    Produite par ``aggregate_thesis_persons`` à partir du dict ``these``
    de l'API theses.fr. ``person`` est le dict brut, transmis tel quel
    au caller pour les effets (extraction d'identifiants, écriture sur
    ``source_authorships``).
    """

    person: dict[str, Any]
    roles: list[str]
    raw_author_name: str
    author_position: int | None
    person_identifiers: dict[str, str] | None
    is_author: bool


def aggregate_thesis_persons(these: dict[str, Any]) -> list[ThesisAuthorship]:
    """Agrège les personnes d'une thèse depuis ``these`` (API theses.fr).

    Itère sur les champs ``auteurs``, ``directeurs``, ``rapporteurs``,
    ``examinateurs``, ``president`` (cf. ``THESES_FIELD_ROLES``). Une
    personne qui apparaît dans plusieurs champs est dédupliquée (clé :
    PPN si présent, sinon ``(nom, prenom)``) et ses rôles sont fusionnés
    via ``merge_roles``.

    En pratique, le cas multi-rôles concerne presque exclusivement le
    président du jury qui est aussi rapporteur (~1 % des authorships
    theses au 2026-05-08).

    ``author_position`` est incrémenté seulement pour les personnes dont
    les rôles fusionnés contiennent ``'author'`` ; ``None`` pour les
    autres rôles (directeurs/rapporteurs/jury/président). Ordre des
    auteurs : celui de la liste ``these["auteurs"]``.
    """
    person_roles: dict[str, dict[str, Any]] = {}

    for field, roles in THESES_FIELD_ROLES.items():
        if field == "president":
            president = these.get("president")
            persons = [president] if president and president.get("nom") else []
        else:
            persons = these.get(field) or []

        for person in persons:
            nom = person.get("nom")
            if not nom:
                continue
            ppn = person.get("ppn")
            key = ppn if ppn else f"name:{nom}:{person.get('prenom', '')}"
            if key not in person_roles:
                person_roles[key] = {"person": person, "roles": []}
            person_roles[key]["roles"].extend(roles)

    out: list[ThesisAuthorship] = []
    position = 0
    for info in person_roles.values():
        person = info["person"]
        merged = merge_roles([info["roles"]])
        is_author = "author" in merged
        prenom = person.get("prenom") or ""
        raw_author_name = (prenom + " " + person["nom"]).strip()
        ppn = person.get("ppn")
        person_identifiers = {"idref": ppn} if ppn else None

        out.append(
            ThesisAuthorship(
                person=person,
                roles=merged,
                raw_author_name=raw_author_name,
                author_position=position if is_author else None,
                person_identifiers=person_identifiers,
                is_author=is_author,
            )
        )
        if is_author:
            position += 1
    return out
