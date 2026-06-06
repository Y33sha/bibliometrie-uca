"""
Service Authorships — orchestrateur des opérations sur `authorships`
et `source_authorships`.

Opérations unitaires sur les authorships consolidées. Le script batch
`build_authorships.py` reste le constructeur principal (reconstruction
complète).

Le SQL vit dans `infrastructure/repositories/authorship_repository.py`.
"""

from sqlalchemy import Connection

from application.audit import emit_event
from application.ports.pipeline.perimeter import PerimeterQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.errors import NotFoundError
from domain.types import JsonValue


def reject_pair(
    publication_id: int,
    person_id: int,
    *,
    repo: AuthorshipRepository,
    audit_repo: AuditRepository | None = None,
) -> dict[str, int]:
    """Rejette durablement une paire (publication, personne) : enregistre que
    cette personne n'est pas l'auteur de cette publication.

    Opération unique partagée par les deux façons de rejeter une contribution
    (depuis la fiche personne et depuis la fiche publication). Trois effets :

    1. Enregistre la paire dans `rejected_authorships`. Ce registre est
       consulté par le matching des personnes et par le rebuild des
       `authorships`, qui ne recréent jamais une paire rejetée — le rejet
       survit donc aux exécutions suivantes du pipeline.
    2. Met à NULL le `person_id` de toutes les `source_authorships` de la paire,
       sur toutes les sources : le lien disparaît côté données sources, et la
       personne ne se verra plus attribuer la forme de nom correspondante.
    3. Supprime la ligne consolidée dans `authorships`, qui n'est plus attestée
       par aucune source.

    Retourne {"detached": N, "deleted_authorships": M}.
    """
    repo.reject_authorship(publication_id, person_id)
    detached = repo.unlink_all_source_authorships_for_pair(publication_id, person_id)
    deleted = repo.delete_orphan_authorships_for_person(person_id)

    emit_event(
        audit_repo,
        "authorship.rejected",
        "publication",
        publication_id,
        {"person_id": person_id},
    )
    return {"detached": detached, "deleted_authorships": deleted}


def exclude_authorship(
    authorship_id: int,
    *,
    repo: AuthorshipRepository,
    person_repo: PersonRepository | None = None,
    audit_repo: AuditRepository | None = None,
) -> dict[str, JsonValue]:
    """Rejette une contribution à partir de sa ligne consolidée (`authorships`).

    Retrouve la paire (publication, personne) à partir de l'`authorship_id`
    puis applique `reject_pair`. Si `person_repo` est fourni, supprime ensuite
    les formes de nom de la personne que plus aucune source n'atteste.

    Si la ligne n'a pas de `person_id`, il n'y a pas de paire à rejeter : on se
    contente de supprimer la ligne.

    Lève NotFoundError si la ligne n'existe pas.
    """
    row = repo.get_authorship_person(authorship_id)
    if not row:
        raise NotFoundError(f"Authorship {authorship_id} introuvable")

    person_id = row["person_id"]
    publication_id = row["publication_id"]
    if person_id is None:
        repo.delete_authorship(authorship_id)
        return {"id": authorship_id, "person_id": None, "publication_id": publication_id}

    reject_pair(publication_id, person_id, repo=repo, audit_repo=audit_repo)
    if person_repo is not None:
        person_repo.delete_orphan_name_forms_for_person(person_id)
    return {"id": authorship_id, "person_id": person_id, "publication_id": publication_id}


def propagate_in_perimeter_for_addresses(
    conn: Connection,
    address_ids: list[int],
    *,
    repo: AuthorshipRepository,
    perimeter_queries: PerimeterQueries,
) -> None:
    """Recalcule in_perimeter sur source_authorships et authorships canoniques
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    perimeter_ids = perimeter_queries.get_persons_structure_ids_list(conn)
    if not perimeter_ids:
        return

    affected_sa_ids = repo.find_source_authorships_by_addresses(address_ids)
    if not affected_sa_ids:
        return

    repo.recompute_in_perimeter_on_source_authorships(affected_sa_ids, perimeter_ids)
    repo.propagate_in_perimeter_to_authorships(affected_sa_ids)
    # `in_perimeter` ci-dessus est recalculé en direct depuis les tables de base
    # (`address_structures`, modifiée par la review) — synchrone et correct. Les
    # matviews `source_authorship_structures` / `authorship_structures`, qui ne
    # portent que l'agrégation des structure_ids dérivées, ne sont PAS rafraîchies
    # ici : maintenues uniquement par le pipeline (staleness bornée à un run,
    # acceptable pour ces dérivées). Cf. docs/chantiers/CODE_background-jobs.md.


def delete_orphan_authorships(person_id: int, *, repo: AuthorshipRepository) -> int:
    """Supprime les authorships canoniques d'une personne qui ne sont plus
    attestées par aucune authorship source. Retourne le nombre d'authorships
    supprimées.
    """
    return repo.delete_orphan_authorships_for_person(person_id)
