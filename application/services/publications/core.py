"""Service Publications — écritures sur l'agrégat Publication, transaction-agnostiques.

Quatre opérations : création, recalcul des métadonnées canoniques depuis les `source_publications`, fusion de deux doublons, marquage d'une paire comme distincte. Toute écriture éditoriale passe par ici, pipeline compris (`create_publication` et `refresh_from_sources` à la réconciliation). Les appelants — phase `publications`, command handlers de l'API, CLI de maintenance — tiennent chacun leur propre frontière transactionnelle et commitent eux-mêmes.
"""

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from domain.errors import DistinctDoiError, NotFoundError, ValidationError
from domain.publications.aggregation import refresh_from_sources as _refresh_aggregate
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_publications.correction import (
    MetadataForCorrection,
    effective_doc_type_for_publication,
)
from domain.sources.registry import SOURCE_PRIORITY

# ── Création ─────────────────────────────────────────────────────────────


def create_publication(
    *,
    title_normalized: str,
    doc_type: str | None,
    pub_year: int,
    doi: str | None,
    repo: PublicationRepository,
) -> int:
    """Crée une publication semée sur le minimum requis par les colonnes NOT NULL, et retourne son id.

    Les valeurs de semis tiennent jusqu'au premier `refresh_from_sources`, qui pose les métadonnées définitives par agrégation une fois les `source_publications` rattachées : `title` reçoit le titre normalisé, `doc_type` vaut `other` quand la source n'en donne aucun, `oa_status` vaut la valeur par défaut, et les métadonnées de publication (journal, titre de conteneur, langue) restent nulles.
    """
    return repo.create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type or "other",
        pub_year=pub_year,
        doi=doi,
        oa_status=OA_STATUS_UNKNOWN_DEFAULT,
    )


# ── Recalcul complet des métadonnées depuis les source_publications ──────


def refresh_from_sources(
    pub_id: int,
    *,
    repo: PublicationRepository,
) -> None:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet : lit toutes les sources attachées, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, persiste. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Deux cas de suppression : la publication sans source rattachée, qu'aucune source n'atteste ; et celle dont le `doc_type` résolu tombe dans `OUT_OF_SCOPE_DOC_TYPES` (invariant « hors périmètre = jamais matérialisé »). Le `delete` détache les `source_publications` (FK ON DELETE SET NULL) et emporte les `authorships` canoniques en cascade.

    Ne touche que la publication reçue et ses sources : quelles `source_publications` forment une même œuvre relève de la réconciliation (`application/pipeline/publications`). Laisse `notes` et `sources` inchangés (`update_sources` les pose).
    """
    pub = repo.find_by_id(pub_id)
    if pub is None:
        return

    sources = repo.get_source_publications(pub_id)
    if not sources:
        repo.delete(pub_id)
        return

    secondary_ids = repo.get_converged_secondary_ids(pub_id)
    # L'agrégation repart des colonnes déjà corrigées par la phase `metadata_correction`, pas du brut.
    _refresh_aggregate(pub, sources, source_priority=SOURCE_PRIORITY, secondary_ids=secondary_ids)
    _apply_canonical_doc_type_correction(pub, repo=repo)

    if pub.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        repo.delete(pub_id)
        return

    repo.save(pub)
    repo.update_sources(pub_id)


def _apply_canonical_doc_type_correction(pub: Publication, *, repo: PublicationRepository) -> None:
    """Rejoue les corrections de `doc_type` sur la publication canonique après l'arbitrage.

    L'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne : la publication porte alors une combinaison — `doc_type` de l'une, `journal_id` de l'autre — qu'aucune `source_publication` ne portait, et qu'aucune correction par source n'a pu voir. Le contrat reçoit les champs que l'agrégation arbitre, dont le `journal_type` du `journal_id` canonique.

    `effective_doc_type_for_publication` écarte les règles lisant un fait propre à un enregistrement source ; les champs correspondants restent nuls ici. L'`oa_status` est hors du rejeu, en entrée comme en sortie — une source corrigée remonte d'elle-même par l'agrégation du statut le plus ouvert, et Unpaywall tranche après vérification.

    Mute `pub.doc_type` et trace la règle dans `pub.meta['corrections']['doc_type']`. Idempotent.
    """
    journal_type = repo.get_journal_type(pub.journal_id) if pub.journal_id is not None else None
    corrected = effective_doc_type_for_publication(
        MetadataForCorrection(
            title=pub.title,
            doc_type=pub.doc_type,
            doi=str(pub.doi) if pub.doi else None,
            journal_id=pub.journal_id,
            oa_status=None,
            urls=None,
            journal_type=journal_type,
            oa_model=None,
            embargo_expired=False,
            self_declared_preprint=False,
        )
    )
    if corrected is not None and corrected.value != pub.doc_type:
        pub.doc_type = corrected.value
        meta = dict(pub.meta or {})
        existing_corrections = meta.get("corrections")
        corrections = dict(existing_corrections) if isinstance(existing_corrections, dict) else {}
        corrections["doc_type"] = corrected.rule.value
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
    4. `refresh_from_sources(target_id)` : recalcule les métadonnées canoniques de la cible depuis ses `source_publications`, à ce stade l'union des siennes et de celles de la source.

    Lève `ValidationError` sur deux identifiants égaux ; `NotFoundError` si target ou source n'existe pas ; `DistinctDoiError` si les deux portent des DOI non-nuls différents.
    """
    if target_id == source_id:
        raise ValidationError("Impossible de fusionner une publication avec elle-même")
    target = repo.find_by_id(target_id)
    source = repo.find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"Publication target #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"Publication source #{source_id} introuvable")

    if target.doi and source.doi and target.doi != source.doi:
        raise DistinctDoiError(target_id, source_id, str(target.doi), str(source.doi))

    repo.merge_into(target_id, source_id)
    refresh_from_sources(target_id, repo=repo)
    emit_event(
        audit_repo,
        "publication.merged",
        "publication",
        target_id,
        {"source_id": source_id},
    )
