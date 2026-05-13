"""Entité ``Authorship`` — entité fille de l'aggregate ``Publication``.

Une `Authorship` représente une signature d'auteur sur une publication
canonique. Au sens DDD strict, c'est une entité fille (lifecycle lié au
root, accès via le root). La FK `authorships.publication_id NOT NULL`
verrouille ce lien côté schéma.

La logique métier touchant aux authorships canoniques (assignation
person↔publication, scope de périmètre, exclusion, rôles) vit ici. Les
chantiers METIER_* qui produisent de la logique sur les authorships y
déposent leurs méthodes dans leurs phases dédiées.

Scaffolding Phase 1 (`CODE_rich-domain-model`) : juste l'identité et les
attributs. Les méthodes de comportement seront ajoutées au fur et à mesure
des chantiers METIER_*.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class Authorship:
    """Signature d'auteur sur une publication canonique.

    Identité : `id` (clé surrogate). FK obligatoire vers le root via
    `publication_id`.
    """

    id: int | None
    publication_id: int
    person_id: int | None = None
    author_position: int | None = None
    in_perimeter: bool = False
    source_manual: bool = False
    excluded: bool = False
    is_corresponding: bool | None = None
    roles: tuple[str, ...] = ()
    structure_ids: tuple[int, ...] = ()
    notes: str | None = None
