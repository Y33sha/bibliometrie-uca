"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module. Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres traitements appellent ces fonctions au lieu de faire du SQL direct.
"""

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from domain.errors import DistinctDoiError, NotFoundError
from domain.publications.aggregation import refresh_from_sources as _refresh_aggregate
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_publications.correction import (
    SourcePublicationForCorrection,
    effective_metadata,
)
from domain.sources.registry import SOURCE_PRIORITY

# ── Recalcul complet des métadonnées depuis les source_publications ──────


def refresh_from_sources(
    pub_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet (pas de COALESCE incrémental qui figerait les valeurs au premier arrivé) : lit TOUS les `source_publications` attachés, applique l'algorithme d'agrégation `refresh_from_sources` (domain) qui mute l'entité Publication en place, et persiste via `repo.save`. Peut corriger des métadonnées obsolètes (ex: `ongoing_thesis` → `thesis` après soutenance).

    **Cas orphelin** : si la publication n'a aucune source rattachée, la règle métier dicte qu'elle ne doit pas exister. Court-circuit : suppression via `repo.delete` + audit event `publication.deleted_orphan`, sans appel à l'agrégation.

    **Cas hors périmètre** : si le `doc_type` canonique résolu appartient à `OUT_OF_SCOPE_DOC_TYPES`, la publication ne doit pas non plus exister (invariant « hors périmètre = jamais matérialisé »). Suppression via `repo.delete` + audit event `publication.deleted_out_of_scope`, après l'arbitrage du type. Les `source_publications` sont détachées (FK ON DELETE SET NULL) et les `authorships` canoniques emportées en cascade.

    L'identité des publications (quelles `source_publications` forment une même œuvre, fusions et scissions comprises) relève de la réconciliation (`application/pipeline/publications`), jamais d'ici : ce recalcul ne touche que la publication reçue et ses propres sources. Une seule publication porte un DOI donné à l'arrivée de la réconciliation, donc `repo.save` ne peut pas heurter la contrainte unique sur le DOI.

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

    previous_doi = pub.doi
    # Les corrections per-record sont déjà persistées sur chaque `source_publication` par la phase
    # `metadata_correction` (colonnes lues par `get_source_publications`) ; l'agrégation repart donc
    # des valeurs corrigées. Mais l'arbitrage choisit `doc_type` et `journal_id` indépendamment :
    # une correction journal-dépendante appliquée à la SP qui a résolu le journal ne suit pas le
    # `journal_id` canonique — on la rejoue sur le canonique après agrégation.
    secondary_ids = repo.get_converged_secondary_ids(pub_id)
    _refresh_aggregate(pub, sources, source_priority=SOURCE_PRIORITY, secondary_ids=secondary_ids)
    _apply_canonical_doc_type_correction(pub, repo=repo)

    # Une publication dont le type résolu est hors périmètre ne doit pas exister — même
    # verdict que le cas orphelin, appliqué au seul endroit qui arbitre le `doc_type`
    # canonique. La suppression détache ses `source_publications` (FK ON DELETE SET NULL) :
    # elles redeviennent orphelines et ne génèrent ni personne ni authorship (les deux
    # chemins exigent une publication) ; les authorships canoniques déjà bâties partent en
    # cascade (FK ON DELETE CASCADE). C'est ce qui rend l'exclusion `doc_type` en aval
    # redondante : hors périmètre ne se matérialise jamais.
    if pub.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        repo.delete(pub_id)
        emit_event(
            audit_repo,
            "publication.deleted_out_of_scope",
            "publication",
            pub_id,
            {"doc_type": pub.doc_type},
        )
        return

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


def _apply_canonical_doc_type_correction(pub: Publication, *, repo: PublicationRepository) -> None:
    """Rejoue les corrections de `doc_type` sur la publication canonique après l'arbitrage.

    L'arbitrage choisit `doc_type` (première source par priorité) et `journal_id` (premier non-nul)
    **indépendamment**, possiblement depuis deux `source_publications` différentes. Une correction
    journal-dépendante (`JOURNAL_TYPE_MEDIA_TO_MEDIA`, …) appliquée par SP en phase
    `metadata_correction` ne fire que sur la SP qui a résolu le journal ; elle ne suit donc pas le
    `journal_id` canonique. On reconstruit une vue de la publication canonique (son `doc_type` arbitré
    + le `journal_type` de son `journal_id` arbitré) et on rejoue `effective_metadata` complète : les
    règles journal-dépendantes s'appliquent alors au journal réellement résolu. Les règles URL n'ont
    pas d'effet ici (le canonique n'agrège pas les URLs), ce qui est voulu — elles restent
    SP-intrinsèques.

    Mute `pub.doc_type` et trace la règle dans `pub.meta['corrections']['doc_type']` si une
    correction s'applique. `meta` étant recalculé à chaque refresh (merge des `meta` sources), la
    trace est éphémère et re-posée à chaque run — pas de brut à préserver côté canonique, contrairement
    au sidecar `raw_metadata` des `source_publications`. Une seule lecture I/O (`journal_type`).
    Idempotent : sur une publication déjà cohérente, aucun changement.
    """
    journal_type = repo.get_journal_type(pub.journal_id) if pub.journal_id is not None else None
    view = SourcePublicationForCorrection(
        id=pub.id or 0,
        source="canonical",
        source_id=str(pub.id),
        title=pub.title,
        pub_year=pub.pub_year,
        doc_type=pub.doc_type,
        doi=str(pub.doi) if pub.doi else None,
        journal_id=pub.journal_id,
        oa_status=pub.oa_status,
        container_title=pub.container_title,
        language=pub.language,
        urls=None,
        external_ids={},
        journal_type=journal_type,
        oa_model=None,
        apc_amount=None,
        raw_metadata={},
        embargo_expired=False,
        # Rejeu canonique limité aux règles journal-dépendantes ; le retypage preprint se fait au
        # niveau SP (puis gagne par arbitrage Crossref), pas ici.
        declares_preprint=False,
    )
    corrected = effective_metadata(view)
    if corrected.doc_type is not None and corrected.doc_type.value != pub.doc_type:
        pub.doc_type = corrected.doc_type.value
        meta = dict(pub.meta or {})
        existing_corrections = meta.get("corrections")
        corrections = dict(existing_corrections) if isinstance(existing_corrections, dict) else {}
        corrections["doc_type"] = corrected.doc_type.rule.value
        meta["corrections"] = corrections
        pub.meta = meta


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
