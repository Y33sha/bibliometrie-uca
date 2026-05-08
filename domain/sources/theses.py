"""Règles métier pures spécifiques à la source theses.fr.

Interprétation des champs propres au schéma theses.fr — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique theses.fr
pour le reste du pipeline.
"""

from dataclasses import dataclass
from typing import Any

from domain.authorship_roles import THESES_FIELD_ROLES, merge_roles
from domain.names import names_compatible
from domain.normalize import normalize_name


def thesis_authors_compatible(
    primary: tuple[str, str] | None,
    claimed: tuple[str, str],
) -> bool:
    """Indique si un auteur candidat est compatible avec l'auteur principal
    d'une thèse existante en BDD.

    Utilisée pour désambiguïser un match par titre+année : si la BDD a
    déjà une thèse avec ce titre cette année, vérifier que l'auteur
    qu'on tente d'attacher correspond bien.

    ``primary`` : ``(nom, prenom)`` de l'auteur principal en BDD (ou
    None si la thèse existante n'a pas d'auteur connu — typiquement
    lors d'une création tronquée). Pas encore normalisés.

    ``claimed`` : ``(nom_normalisé, prenom_normalisé)`` de l'auteur
    candidat (la forme normalisée vient du caller — déjà préparée
    avant lookup).

    Cascade :
      1. Pas d'auteur connu (``primary is None`` ou nom vide après
         normalisation) → accepte. Le titre+année font foi quand on
         n'a rien d'autre à comparer.
      2. ``names_compatible`` standard (ordre flexible nom/prénom +
         initiales).
      3. Fallback tokens identiques avec garde ``len >= 2`` : gère
         les particules type « Le », « Ben », « Da » que
         ``names_compatible`` peut rater quand elles atterrissent
         côté nom vs côté prénom selon les sources. Garde-fou
         minimal sur le nombre de tokens pour éviter qu'un simple
         prénom commun soit considéré « identique ».
    """
    if primary is None:
        return True
    ln = normalize_name(primary[0])
    fn = normalize_name(primary[1])
    if not ln:
        return True
    if names_compatible(claimed[0], claimed[1], ln, fn):
        return True
    tokens_a = set(f"{claimed[0]} {claimed[1]}".split())
    tokens_b = set(f"{ln} {fn}".split())
    return tokens_a == tokens_b and len(tokens_a) >= 2


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
    au caller pour les effets (upsert ``source_persons`` notamment).
    """

    person: dict[str, Any]
    roles: list[str]
    raw_author_name: str
    author_position: int | None
    identifiers: dict[str, str] | None
    is_author: bool


def aggregate_thesis_persons(these: dict) -> list[ThesisAuthorship]:
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
        identifiers = {"idref": ppn} if ppn else None

        out.append(
            ThesisAuthorship(
                person=person,
                roles=merged,
                raw_author_name=raw_author_name,
                author_position=position if is_author else None,
                identifiers=identifiers,
                is_author=is_author,
            )
        )
        if is_author:
            position += 1
    return out
