"""Pool de DOI à cross-importer et journal des DOI introuvables (`doi_lookups`).

`get_cross_import_dois` bâtit la liste des DOI présents ailleurs mais absents de la cible ; `record_doi_not_found` mémorise les misses pour les exclure du pool en backoff. Le commit est à la charge de l'appelant.
"""

from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES

# `target source → RA attendue côté doi_prefixes` : pour crossref/datacite, les DOIs candidats sont filtrés sur la RA du préfixe (`ra` NULL accepté).
# Sources absentes (hal, openalex, wos, scanr) : aucun filtre RA.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
    "datacite": "DataCite",
}


DOI_LOOKUP_RETRY_DAYS = 30
"""Délai (jours) avant de re-tenter un DOI introuvable sur une source non native.

Un DOI absent d'une source *autre que sa source native* n'est pas définitivement absent : la source peut l'indexer plus tard. On mémorise le miss dans `doi_lookups` avec `next_retry = now() + DOI_LOOKUP_RETRY_DAYS`, ce qui borne le pool de re-tentatives (sans ce backoff, ces DOI seraient réinterrogés à chaque run, coût API croissant).
"""

_RECORD_DOI_NOT_FOUND_SQL = text(
    """
    INSERT INTO doi_lookups (source, doi, not_found_at, next_retry)
    VALUES (
        CAST(:source AS source_type), :doi, now(),
        CASE WHEN :permanent THEN NULL ELSE now() + make_interval(days => :days) END
    )
    ON CONFLICT (source, doi) DO UPDATE SET
        not_found_at = now(),
        next_retry = CASE WHEN :permanent THEN NULL ELSE now() + make_interval(days => :days) END
    """
)


def record_doi_not_found(
    conn: Connection, source: str, doi: str, *, permanent: bool = False
) -> None:
    """Mémorise (ou ré-arme) un miss de cross-import par DOI dans `doi_lookups`.

    Appelé par les adapters `fetch_missing_doi` quand un DOI cherché est absent de la source. `permanent=False` (hal, openalex, wos, scanr) : miss temporaire, `next_retry` repousse la prochaine tentative de `DOI_LOOKUP_RETRY_DAYS` jours — ces sources peuvent indexer le DOI plus tard. `permanent=True` (crossref, datacite, dont le DOI est l'identifiant natif) : `next_retry = NULL`, miss définitif jamais retenté. Ne commit pas — l'appelant s'en charge.

    Le DOI est normalisé par `clean_doi` avant écriture : `doi_lookups.doi` sert de clé d'exclusion comparée à des DOI déjà normalisés (cf. `get_cross_import_dois`) — toute forme non canonique manquerait l'exclusion.
    """
    conn.execute(
        _RECORD_DOI_NOT_FOUND_SQL,
        {
            "source": source,
            "doi": clean_doi(doi),
            "days": DOI_LOOKUP_RETRY_DAYS,
            "permanent": permanent,
        },
    )


def get_cross_import_dois(conn: Connection, target: str) -> list[str]:
    """Retourne les DOI présents dans les autres sources mais absents de la cible.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_publications.doi` (DOI primaire) ∪ `external_ids.related_dois` (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de `external_ids.arxiv_id` (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne cross-importer que des DOI de publications in-périmètre coupe la propagation de cross-imports hors-périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Le SQL compare les `doi` par égalité directe. Les candidats retenus sont normalisés via `clean_doi` et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

    Exclut les DOI en backoff dans `doi_lookups` (miss cross-import récent sur la cible dont `next_retry` n'est pas encore atteint). Le pool est auto-borné et convergent : 1er pass tente tout, les misses reçoivent un `next_retry`, les passes suivantes ne retentent que les DOI dont le délai est écoulé.

    Pour les cibles présentes dans `_TARGET_RA`, ajoute un LEFT JOIN sur `doi_prefixes` pour filtrer les DOIs dont la RA résolue ne correspond pas (les NULL — préfixe non résolu — sont conservés).

    Args:
        conn: `Connection` SA.
        target: clé source cible (hal, openalex, wos, scanr, crossref)
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = _TARGET_RA.get(target)
    join_clause = (
        "LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)" if target_ra else ""
    )
    # Exclusion du target : `source IS DISTINCT FROM` (relations à source NULL candidates pour toutes les cibles) + `NOT IN (staging du target)`.
    prefix_filter = " AND (dp.ra = :target_ra OR dp.ra IS NULL)" if target_ra else ""
    query = f"""
        SELECT DISTINCT c.doi
        FROM candidate_dois c
        {join_clause}
        WHERE c.source IS DISTINCT FROM :target
          AND c.doi NOT IN (
                  SELECT doi FROM staging WHERE source = :target AND doi IS NOT NULL
              ){prefix_filter}
          AND NOT EXISTS (
              SELECT 1 FROM doi_lookups l
              WHERE l.source = :target AND l.doi = c.doi
                AND (l.next_retry IS NULL OR l.next_retry > now())
          )
        ORDER BY c.doi
    """
    params: dict[str, str] = {"target": target}
    if target_ra:
        params["target_ra"] = target_ra
    rows = conn.execute(text(query), params).scalars()
    # Re-nettoyage des candidats (idempotent) : `staging.doi` peut porter des DOI non normalisés ; `dict.fromkeys` dédoublonne en préservant l'ordre.
    return list(dict.fromkeys(c for d in rows if (c := clean_doi(d))))
