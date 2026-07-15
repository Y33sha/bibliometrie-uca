"""Attribuer à une personne des authorships sources orphelines.

Ces deux opérations (unitaire et par lot) sont exposées par l'API admin (`POST /api/admin/orphan-authorships/...`) — actions utilisateur, hors pipeline. À l'interface entre `persons`, `source_authorships` et `publications`, leur issue est la création ou la mise à jour de lignes dans `authorships`.

Le helper privé `_refresh_authorship_from_sources` chaîne les cinq opérations atomiques du port qui recomposent une authorship pour une paire (publication, personne) depuis ses source_authorships.
"""

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import (
    AuthorshipAlreadyAssignedError,
    NotFoundError,
    RejectedPairError,
)
from domain.sources.registry import (
    AUTHOR_SOURCES,
    SOURCE_PRIORITY,
    require_known_source,
)


def _resolve_rejection(
    person_id: int,
    publication_ids: list[int],
    *,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository | None,
    force: bool,
) -> None:
    """Pré-contrôle des paires rejetées avant une réassignation.

    Cherche, parmi les `publication_ids`, celles dont la paire avec
    `person_id` figure dans `rejected_authorships`. Si au moins une est
    rejetée :
    - sans `force` : lève `RejectedPairError` (→ 409) listant les paires et
      leur date de rejet, pour que l'UI demande confirmation ;
    - avec `force` : lève le rejet de chaque paire (suppression du registre +
      événement d'audit), ce qui laisse la réassignation recréer le lien.
    """
    rejected = [
        (pub_id, at)
        for pub_id in publication_ids
        if (at := authorship_repo.find_rejected_authorship(pub_id, person_id)) is not None
    ]
    if not rejected:
        return
    if not force:
        raise RejectedPairError(
            [
                {"publication_id": pub_id, "person_id": person_id, "rejected_at": at.isoformat()}
                for pub_id, at in rejected
            ]
        )
    for pub_id, _ in rejected:
        authorship_repo.delete_rejected_authorship(pub_id, person_id)
        emit_event(
            audit_repo, "authorship.unrejected", "publication", pub_id, {"person_id": person_id}
        )


def assign_orphan_authorship(
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
    force: bool = False,
) -> None:
    """Attribue une signature source orpheline (`person_id IS NULL`) à une personne.

    1. Valide la source
    2. Pré-contrôle de rejet : si la paire (publication, personne) est rejetée
       et que `force` est faux, lève `RejectedPairError` ; avec `force`, lève
       le rejet d'abord (cf. `_resolve_rejection`)
    3. Pose `person_id` sur la signature source, si elle est orpheline
    4. Ajoute la forme de nom
    5. Crée/met à jour l'authorship canonique + FK source

    Lève `ValidationError` sur une source hors registre, `NotFoundError` si la signature n'existe pas, `AuthorshipAlreadyAssignedError` si elle porte déjà une personne.
    """
    require_known_source(source)

    publication_id = repo.find_publication_id_for_source_authorship(source, authorship_id)
    if publication_id is not None:
        _resolve_rejection(
            person_id,
            [publication_id],
            authorship_repo=authorship_repo,
            audit_repo=audit_repo,
            force=force,
        )

    row = repo.assign_orphan_sa(person_id, source, authorship_id)
    if row is None:
        # L'UPDATE ne pose `person_id` que sur une signature orpheline : son échec signale une
        # signature absente ou déjà rattachée. Un `owner` nul tranche pour l'absence — sur une
        # signature orpheline et existante, l'UPDATE aboutit.
        owner = repo.find_source_authorship_owner(source, authorship_id)
        if owner is None:
            raise NotFoundError(f"Signature {source} #{authorship_id} introuvable")
        raise AuthorshipAlreadyAssignedError(source, authorship_id, owner)

    # Épingler la résolution admin (must-link grain signature) : le pipeline la
    # relira comme entrée fixe et ne re-dérivera jamais cette signature.
    authorship_repo.pin_authorships([authorship_id], person_id)

    # Ajouter la forme de nom
    if row["author_name_normalized"]:
        repo.add_name_form(person_id, row["author_name_normalized"], source=source)

    # Recomposer l'authorship canonique pour la paire (pub, person)
    if publication_id is not None:
        _refresh_authorship_from_sources(person_id, publication_id, repo=repo)
    # `authorship_structures` (agrégation des structure_ids) maintenue uniquement
    # par le pipeline — pas de refresh sur action admin (staleness bornée à un run).


def batch_assign_orphan_authorships(
    person_id: int,
    sa_ids: list[int],
    *,
    repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
    force: bool = False,
) -> int:
    """Attribue en batch plusieurs authorships sources orphelines à une personne.

    Pré-contrôle de rejet sur l'ensemble des publications couvertes (cf.
    `_resolve_rejection`) : sans `force`, une seule paire rejetée bloque tout
    le lot (`RejectedPairError`) ; avec `force`, les rejets sont d'abord levés.

    Retourne le nombre de source_authorships effectivement rattachées
    (celles qui étaient orphelines).
    """
    if not sa_ids:
        return 0

    publication_ids = repo.find_publication_ids_for_source_authorships(sa_ids)
    _resolve_rejection(
        person_id,
        publication_ids,
        authorship_repo=authorship_repo,
        audit_repo=audit_repo,
        force=force,
    )

    assigned = repo.assign_orphan_source_authorships_to_person(person_id, sa_ids)
    authorship_repo.pin_authorships(sa_ids, person_id)
    repo.create_authorships_from_sources(person_id, sa_ids, SOURCE_PRIORITY)
    repo.link_source_authorships_to_authorships(person_id, sa_ids)

    for name_form in repo.get_distinct_name_forms_from_source_authorships(sa_ids):
        repo.add_name_form(person_id, name_form)

    # `authorship_structures` (agrégation des structure_ids) maintenue uniquement
    # par le pipeline — pas de refresh sur action admin (staleness bornée à un run).
    return assigned


def _refresh_authorship_from_sources(
    person_id: int,
    publication_id: int,
    *,
    repo: PersonRepository,
) -> None:
    """Recompose une authorship pour la paire (publication, personne) depuis ses source_authorships actives.

    Chaîne :
    1. INSERT IF MISSING dans authorships
    2. Pose la FK source_authorships.authorship_id (sources non exclues)
    3. Recalcule author_position (par priorité de source) et is_corresponding (bool_or)
    4. Recalcule in_perimeter (agrégation OR ; les structures dérivées vivent dans la matview `authorship_structures`, rafraîchie par l'appelant)
    """
    repo.insert_authorship_if_missing(publication_id, person_id)
    repo.link_source_authorships_to_authorship(publication_id, person_id)
    repo.recompute_authorship_author_position_and_corresponding(
        publication_id,
        person_id,
        SOURCE_PRIORITY,
    )
    repo.recompute_authorship_in_perimeter(publication_id, person_id, AUTHOR_SOURCES)
