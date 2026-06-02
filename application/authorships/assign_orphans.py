"""Use case : attribuer à une personne des authorships sources orphelines.

Ces deux use cases (single + batch) sont exposés par l'API admin
(`POST /api/admin/orphan-authorships/...`) — actions utilisateur, hors
pipeline. À l'interface entre `persons`, `source_authorships` et
`publications`, mais leur issue est la création / mise à jour de lignes
dans la table `authorships`.

Le helper privé `_refresh_authorship_from_sources` chaîne les 5
opérations atomiques du port qui recomposent une authorship pour une
paire (publication, person) depuis ses source_authorships.
"""

from application.ports.repositories.person_repository import PersonRepository
from domain.errors import ValidationError
from domain.sources.registry import (
    ALL_SOURCES_SET,
    AUTHOR_SOURCES,
    SOURCE_PRIORITY,
)


def assign_orphan_authorship(
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    repo: PersonRepository,
) -> bool:
    """Attribue une authorship orpheline (person_id IS NULL) à une personne.

    1. Valide la source
    2. Met person_id sur l'authorship source (seulement si elle est orpheline)
    3. Ajoute la forme de nom
    4. Crée/met à jour l'authorship canonique + FK source

    Retourne True si l'authorship a été attribuée, False sinon.
    """
    if source not in ALL_SOURCES_SET:
        raise ValidationError(f"Source inconnue : {source}")

    row = repo.assign_orphan_sa(person_id, source, authorship_id)
    if not row:
        return False

    # Ajouter la forme de nom
    if row["author_name_normalized"]:
        repo.add_name_form(person_id, row["author_name_normalized"], source=source)

    # Recomposer l'authorship canonique pour la paire (pub, person)
    publication_id = repo.find_publication_id_for_source_authorship(source, authorship_id)
    if publication_id is not None:
        _refresh_authorship_from_sources(person_id, publication_id, repo=repo)
        # Les structures dérivées vivent dans la matview `authorship_structures`.
        repo.refresh_authorship_structures()
    return True


def batch_assign_orphan_authorships(
    person_id: int,
    sa_ids: list[int],
    *,
    repo: PersonRepository,
) -> int:
    """Attribue en batch plusieurs authorships sources orphelines à une personne.

    Retourne le nombre de source_authorships effectivement rattachées
    (celles qui étaient orphelines).
    """
    if not sa_ids:
        return 0

    assigned = repo.assign_orphan_source_authorships_to_person(person_id, sa_ids)
    repo.create_authorships_from_sources(person_id, sa_ids, SOURCE_PRIORITY)
    repo.link_source_authorships_to_authorships(person_id, sa_ids)

    for name_form in repo.get_distinct_name_forms_from_source_authorships(sa_ids):
        repo.add_name_form(person_id, name_form)

    # Les structures dérivées vivent dans la matview `authorship_structures`.
    repo.refresh_authorship_structures()
    return assigned


def _refresh_authorship_from_sources(
    person_id: int,
    publication_id: int,
    *,
    repo: PersonRepository,
) -> None:
    """Recompose une authorship pour la paire (publication, person) depuis
    ses source_authorships actives.

    Chaîne :
    1. INSERT IF MISSING dans authorships
    2. Pose la FK source_authorships.authorship_id (sources non exclues)
    3. Recalcule author_position (par priorité de source) et is_corresponding
       (bool_or)
    4. Recalcule in_perimeter (agrégation OR ; les structures dérivées vivent
       dans la matview `authorship_structures`, rafraîchie par le caller)
    """
    repo.insert_authorship_if_missing(publication_id, person_id)
    repo.link_source_authorships_to_authorship(publication_id, person_id)
    repo.recompute_authorship_author_position_and_corresponding(
        publication_id,
        person_id,
        SOURCE_PRIORITY,
    )
    repo.recompute_authorship_in_perimeter(publication_id, person_id, AUTHOR_SOURCES)
