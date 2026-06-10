"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module. Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres traitements appellent ces fonctions au lieu de faire du SQL direct.
"""

from dataclasses import replace

from application.audit import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PubByDoi, PublicationRepository
from domain.errors import DistinctDoiError, NotFoundError
from domain.publications.aggregation import (
    first_non_null,
)
from domain.publications.aggregation import (
    refresh_from_sources as _refresh_aggregate,
)
from domain.publications.correction import effective_metadata
from domain.publications.deduplication import (
    resolve_doi_conflict as _domain_resolve_doi_conflict,
)
from domain.publications.identifiers import DOI
from domain.source_publications.views import SourcePublicationWithJournalView
from domain.sources.registry import SOURCE_PRIORITY


def find_by_doi(doi: str, *, repo: PublicationRepository) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    return repo.find_by_doi(doi)


def find_by_nnt(nnt: str, *, repo: PublicationRepository) -> int | None:
    """Cherche une publication via NNT (source_publications.external_ids)."""
    return repo.find_by_nnt(nnt)


def find_thesis_by_title(
    title_normalized: str,
    pub_year: int,
    *,
    repo: PublicationRepository,
) -> list[int]:
    """Cherche des thèses par titre normalisé + année (sans journal_id)."""
    return repo.find_thesis_by_title(title_normalized, pub_year)


def resolve_doi_conflict(
    doi: str,
    doc_type: str,
    title_normalized: str,
    existing: PubByDoi,
    *,
    repo: PublicationRepository,
) -> tuple[str | None, int | None]:
    """Applique la règle `domain.publication.resolve_doi_conflict` et ses effets.

    Délègue la décision au domaine (fonction pure), puis réalise l'effet
    de bord `clear_doi` via le repository quand la règle le demande.

    Retourne (doi_corrige, publication_id_si_fusion).
    """
    decision = _domain_resolve_doi_conflict(
        new_doi=doi,
        new_doc_type=doc_type,
        new_title_normalized=title_normalized,
        existing_doc_type=existing.doc_type,
        existing_title_normalized=existing.title_normalized,
        existing_id=existing.id,
    )
    if decision.clear_existing_doi:
        repo.clear_doi(existing.id)
    return decision.accepted_doi, decision.merge_with_id


# ── Recalcul complet des métadonnées depuis les source_publications ──────


def apply_corrections(sp: SourcePublicationWithJournalView) -> SourcePublicationWithJournalView:
    """Applique `effective_metadata` à une vue de source publication et renvoie une vue « effective » : la vue inchangée si aucune correction ne modifie une valeur, sinon une copie avec les champs corrigés et un audit `meta.<field>_corrected_by` pour chaque champ effectivement changé.

    L'audit n'est posé que quand la valeur change réellement : une règle qui « corrige » vers la valeur déjà présente (ex. une SP theses.fr native déjà en `thesis`) n'est pas tracée comme une correction.
    """
    corrected = effective_metadata(sp)
    if corrected.is_empty():
        return sp

    meta = dict(sp.meta or {})
    new_journal_id = sp.journal_id
    new_doc_type = sp.doc_type
    new_oa_status = sp.oa_status
    changed = False

    if corrected.journal_id is not None and corrected.journal_id.value != sp.journal_id:
        new_journal_id = corrected.journal_id.value
        meta["journal_id_corrected_by"] = corrected.journal_id.rule.value
        changed = True
    if corrected.doc_type is not None and corrected.doc_type.value != sp.doc_type:
        new_doc_type = corrected.doc_type.value
        meta["doc_type_corrected_by"] = corrected.doc_type.rule.value
        changed = True
    if corrected.oa_status is not None and corrected.oa_status.value != sp.oa_status:
        new_oa_status = corrected.oa_status.value
        meta["oa_status_corrected_by"] = corrected.oa_status.rule.value
        changed = True

    if not changed:
        return sp
    return replace(
        sp,
        journal_id=new_journal_id,
        doc_type=new_doc_type,
        oa_status=new_oa_status,
        meta=meta,
    )


def refresh_from_sources(
    pub_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet (pas de COALESCE incrémental qui figerait les valeurs au premier arrivé) : lit TOUS les `SourcePublication` attachés, applique l'algorithme d'agrégation `refresh_from_sources` (domain) qui mute l'entité Publication en place, et persiste via `repo.save`. Peut corriger des métadonnées obsolètes (ex: `ongoing_thesis` → `thesis` après soutenance).

    **Cas orphelin** : si la publication n'a aucune source rattachée, la règle métier dicte qu'elle ne doit pas exister. Court-circuit : suppression via `repo.delete` + audit event `publication.deleted_orphan`, sans appel à l'agrégation.

    Auto-fusion sur conflit DOI : si la promotion du DOI agrégé entre en collision avec une autre publication qui occupe déjà ce DOI, cette dernière est absorbée dans `pub_id` avant le save — au lieu de laisser remonter une violation de la contrainte unique. `pub_id` reste vivant pour le caller. La fusion est tracée via l'audit event `publication.merged`.

    Si `audit_repo` est fourni et que le DOI canonique change effectivement (passage d'une valeur à une autre, ou perte du DOI), un événement `publication.doi_changed` est émis avec l'ancienne et la nouvelle valeur. Pas d'event sur l'attribution initiale (passage de None à une valeur) ni quand la valeur reste identique.

    Ne touche PAS à `notes` ni à `sources` (utiliser `update_sources` séparément).
    """
    pub = repo.find_by_id(pub_id)
    if pub is None:
        return

    sources = repo.get_source_publications(pub_id)
    if not sources:
        # Pub orpheline : la règle métier dicte qu'une publication non attestée par aucune source n'a pas de raison d'exister.
        repo.delete(pub_id)
        emit_event(audit_repo, "publication.deleted_orphan", "publication", pub_id, {})
        return

    # Si le DOI à promouvoir est déjà occupé par une autre publication, fusionner d'abord pour éviter une violation de la contrainte unique `publications_doi_lower_key`. Cas typique : une thèse avec un DOI ABES (10.70675/…) créée en double — une fois via OpenAlex (DOI seul, NNT inconnu) et une fois via theses.fr/HAL (NNT seul, DOI publié plus tard). Quand le DOI finit par apparaître dans une `source_publication`, sa promotion collisionne avec la pub OpenAlex. La fusion absorbe l'autre dans `pub_id` (qui reste vivant pour le caller).
    #
    # Le DOI brut est normalisé via le VO `DOI` avant le lookup : c'est cette forme normalisée (suffixe `.vN` strippé, lowercased) qui sera posée par l'agrégation. Le pré-merge doit chercher la même forme, sinon des collisions échappent au mécanisme.
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    sorted_sources = sorted(sources, key=lambda s: rank.get(s.source, 99))
    new_doi_raw = first_non_null(sorted_sources, "doi")
    new_doi_vo = DOI.try_parse(new_doi_raw) if new_doi_raw else None
    if new_doi_vo:
        existing = repo.find_by_doi(str(new_doi_vo))
        if existing and existing.id != pub_id:
            merge_publications(pub_id, existing.id, repo=repo, audit_repo=audit_repo)
            sources = repo.get_source_publications(pub_id)
            # Recharger pub : ses attributs ont pu être enrichis via Publication.absorb pendant merge_publications.
            pub = repo.find_by_id(pub_id)
            if pub is None:
                return

    previous_doi = pub.doi
    effective_sources = [apply_corrections(s) for s in sources]
    _refresh_aggregate(pub, effective_sources, source_priority=SOURCE_PRIORITY)
    repo.save(pub)
    repo.update_sources(pub_id)

    if previous_doi is not None and pub.doi != previous_doi:
        emit_event(
            audit_repo,
            "publication.doi_changed",
            "publication",
            pub_id,
            {
                "previous_doi": str(previous_doi),
                "new_doi": str(pub.doi) if pub.doi else None,
            },
        )


def mark_distinct(
    pub_id_a: int,
    pub_id_b: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Marque deux publications comme distinctes (non-doublon) dans
    `distinct_publications`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = repo.mark_distinct(pub_id_a, pub_id_b)
    if inserted:
        emit_event(
            audit_repo,
            "publication.marked_distinct",
            "publication",
            inserted[0],
            {"other_id": inserted[1]},
        )


def merge_publications(
    target_id: int,
    source_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la publication `source_id` dans `target_id`.

    Orchestration domain-driven :

    1. Charge `target` et `source` comme entités `Publication` via le repo.
    2. Garde « 1 DOI = 1 publication » : si les deux portent des DOI non-nuls
       différents, refuse (`DistinctDoiError`) — ce sont des œuvres distinctes,
       quelle que soit la clé qui les a rapprochées.
    3. `target.absorb(source)` : enrichissement métadonnées en mémoire (règle pairwise OA, COALESCE des scalaires nullable, union countries) — vit dans l'aggregate.
    4. `repo.merge_into(target_id, source_id)` : plumbing FK (transfert des source_publications + authorships avec dédup, cleanup distinct_publications, DELETE de la ligne source).
    5. `repo.save(target)` : persistance des métadonnées enrichies, après le `merge_into`.
    6. Recalcule `sources` agrégé.
    7. Émet l'événement d'audit.

    Lève `NotFoundError` si target ou source n'existe pas ; `DistinctDoiError`
    si les deux portent des DOI non-nuls différents.
    """
    target = repo.find_by_id(target_id)
    source = repo.find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"Publication target #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"Publication source #{source_id} introuvable")

    if target.doi and source.doi and target.doi != source.doi:
        raise DistinctDoiError(target_id, source_id, str(target.doi), str(source.doi))

    target.absorb(source)
    repo.merge_into(target_id, source_id)
    repo.save(target)
    repo.update_sources(target_id)
    emit_event(
        audit_repo,
        "publication.merged",
        "publication",
        target_id,
        {"source_id": source_id},
    )
