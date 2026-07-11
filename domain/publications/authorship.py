"""Entité `Authorship` — entité fille de l'aggregate `Publication`.

Une `Authorship` représente une signature d'auteur sur une publication
canonique. Au sens DDD strict, c'est une entité fille (lifecycle lié au
root, accès via le root). La FK `authorships.publication_id NOT NULL`
verrouille ce lien côté schéma.

La logique métier touchant aux authorships canoniques (assignation
person↔publication, scope de périmètre, rôles) vit ici. Le rejet d'une
paire (« cette personne n'est pas l'auteur ») n'est pas un attribut de
l'entité : il vit dans le store `rejected_authorships`.
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
    is_corresponding: bool | None = None
    roles: tuple[str, ...] = ()
    structure_ids: tuple[int, ...] = ()
