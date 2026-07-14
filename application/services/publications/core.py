"""Service Publications — accès exclusif en écriture à la table `publications`.

Toute création ou mise à jour d'une publication passe par ce module : les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres traitements appellent ces fonctions, sans SQL direct.
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

    Recalcul complet : lit TOUS les `source_publications` attachés, applique l'algorithme d'agrégation `refresh_from_sources` (domain) qui mute l'entité Publication en place, et persiste via `repo.save`. Peut corriger des métadonnées périmées (ex : `ongoing_thesis` → `thesis` après soutenance).

    **Cas orphelin** : une publication sans aucune source rattachée n'a pas lieu d'exister. Suppression via `repo.delete` + audit `publication.deleted_orphan`, sans agrégation.

    **Cas hors périmètre** : si le `doc_type` canonique résolu appartient à `OUT_OF_SCOPE_DOC_TYPES`, la publication est supprimée de même (invariant « hors périmètre = jamais matérialisé »), via `repo.delete` + audit `publication.deleted_out_of_scope`. Ses `source_publications` sont détachées (FK ON DELETE SET NULL), ses `authorships` canoniques emportés en cascade.

    L'identité des publications (quelles `source_publications` forment une même œuvre) relève de la réconciliation (`application/pipeline/publications`), jamais d'ici : ce recalcul ne touche que la publication reçue et ses sources. Une seule publication porte un DOI donné à ce stade : `repo.save` respecte la contrainte d'unicité.

    Si `audit_repo` est fourni et que le DOI canonique change (d'une valeur à une autre, ou perte), un événement `publication.doi_changed` porte l'ancienne et la nouvelle valeur. Rien sur l'attribution initiale (None → valeur) ni sur une valeur inchangée.

    Laisse `notes` et `sources` inchangés (utiliser `update_sources` séparément).
    """
    pub = repo.find_by_id(pub_id)
    if pub is None:
        return

    sources = repo.get_source_publications(pub_id)
    if not sources:
        # Publication orpheline : la règle métier dicte qu'une publication non attestée par aucune source n'a pas de raison d'exister.
        repo.delete(pub_id)
        emit_event(audit_repo, "publication.deleted_orphan", "publication", pub_id, {})
        return

    previous_doi = pub.doi
    # Les corrections par enregistrement sont déjà persistées sur chaque `source_publication` par la
    # phase `metadata_correction` (colonnes lues par `get_source_publications`) : l'agrégation repart
    # des valeurs corrigées. L'arbitrage choisit `doc_type` et `journal_id` indépendamment : une
    # correction journal-dépendante appliquée à la source qui a résolu le journal ne suit pas le
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

    L'arbitrage choisit `doc_type` (première source par priorité) et `journal_id` (premier non-nul) **indépendamment**, possiblement depuis deux `source_publications` différentes. Une correction journal-dépendante (`JOURNAL_TYPE_MEDIA_TO_MEDIA`, …) appliquée par `source_publication` en phase `metadata_correction` ne se déclenche que sur celle qui a résolu le journal ; elle ne suit pas le `journal_id` canonique. On reconstruit une vue de la publication canonique (son `doc_type` arbitré + le `journal_type` de son `journal_id` arbitré) et on rejoue `effective_metadata` complète : les règles journal-dépendantes s'appliquent alors au journal réellement résolu. Les règles URL n'ont pas d'effet ici (le canonique n'agrège pas les URLs) : elles restent propres aux `source_publications`.

    Mute `pub.doc_type` et trace la règle dans `pub.meta['corrections']['doc_type']` si une correction s'applique. `meta` est recalculé à chaque refresh (fusion des `meta` sources) : la trace est éphémère, re-posée à chaque run, sans brut à préserver côté canonique. Une seule lecture I/O (`journal_type`). Idempotent : sur une publication déjà cohérente, aucun changement.
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
    """Marque deux publications comme distinctes (non-doublon) dans `distinct_publications`. Idempotent.

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

    Orchestration :

    1. Charge `target` et `source` comme entités `Publication` via le repo.
    2. Garde « 1 DOI = 1 publication » : si les deux portent des DOI non-nuls différents, refuse (`DistinctDoiError`) — ce sont des œuvres distinctes, quelle que soit la clé qui les a rapprochées.
    3. `repo.merge_into(target_id, source_id)` : reprise des clés étrangères (transfert des `source_publications` et authorships avec dédup, repointage des `distinct_publications`, DELETE de la ligne source).
    4. `refresh_from_sources(target_id)` : recalcule les métadonnées canoniques de la cible depuis ses `source_publications`, à ce stade l'union des siennes et de celles de la source. Même règle d'agrégation que partout ailleurs (statut OA le plus ouvert, scalaires par priorité de source) : aucune divergence selon le chemin de fusion.

    Lève `NotFoundError` si target ou source n'existe pas ; `DistinctDoiError` si les deux portent des DOI non-nuls différents.
    """
    target = repo.find_by_id(target_id)
    source = repo.find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"Publication target #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"Publication source #{source_id} introuvable")

    if target.doi and source.doi and target.doi != source.doi:
        raise DistinctDoiError(target_id, source_id, str(target.doi), str(source.doi))

    repo.merge_into(target_id, source_id)
    refresh_from_sources(target_id, repo=repo, audit_repo=audit_repo)
    emit_event(
        audit_repo,
        "publication.merged",
        "publication",
        target_id,
        {"source_id": source_id},
    )
