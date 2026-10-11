"""Sélection des DOI à chercher dans une source cible, pour la phase `fetch_missing`.

`get_missing_dois` bâtit la liste des DOI présents ailleurs mais absents de la cible.
"""

from sqlalchemy import Connection, ScalarResult, text

from domain.publications.identifiers import clean_doi
from domain.source_publications.external_ids import ExternalIdType
from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES
from infrastructure.pipeline.fetch_missing.failed_lookups import pending_failed_lookup_sql

# `target source → RA attendue côté doi_prefixes` : pour crossref/datacite, les DOIs candidats sont filtrés sur la RA du préfixe (`ra` NULL accepté).
# Sources absentes (hal, openalex, wos, scanr) : aucun filtre RA.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
    "datacite": "DataCite",
}


def get_missing_dois(conn: Connection, target: str) -> list[str]:
    """Retourne les DOI présents dans les autres sources mais absents de la cible.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_publications.doi` (DOI primaire) ∪ `external_ids.related_dois` (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de `external_ids.arxiv_id` (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne chercher que les DOI de publications in-périmètre évite de rapatrier des documents hors périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Exclut les DOI que la cible porte déjà, en `source_publications.doi` comme en `external_ids.related_dois` : une source rend un même document pour l'un ou l'autre de ses identifiants, si bien qu'un DOI secondaire ramènerait un document déjà présent.

    Le SQL compare les `doi` par égalité directe. Les candidats retenus sont normalisés via `clean_doi` et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

    Exclut les DOI dont la recherche dans la cible a échoué et attend encore sa reprise (`failed_lookups`). Le pool se borne donc de lui-même : un DOI introuvable en sort jusqu'à l'échéance de son délai, ou définitivement quand il est l'identifiant natif de la cible.

    Pour les cibles présentes dans `_TARGET_RA`, retient seulement les DOI dont le préfixe est résolu vers l'agence de la cible. Un préfixe pas encore résolu attend la phase `resolve_ra`, plus loin dans le run : son DOI est cherché au run suivant, et jamais auprès des deux API.

    Args:
        conn: `Connection` SA.
        target: clé source cible (hal, openalex, wos, scanr, crossref)
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = _TARGET_RA.get(target)
    join_clause = (
        "JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)" if target_ra else ""
    )
    # Exclusion du target : `source IS DISTINCT FROM` (relations à source NULL candidates pour toutes les cibles) + absent du staging du target + absent des DOI que la cible porte déjà. `NOT EXISTS` plutôt que `NOT IN` : un NULL dans la sous-requête viderait la sélection.
    prefix_filter = " AND dp.ra = :target_ra" if target_ra else ""
    pending = pending_failed_lookup_sql(source_sql=":target", id_type="doi", value_sql="c.doi")
    query = f"""
        WITH deja_connus AS (
            SELECT sp.doi
            FROM source_publications sp
            WHERE sp.source = CAST(:target AS source_type) AND sp.doi IS NOT NULL
            UNION
            SELECT d.value
            FROM source_publications sp
            CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') d(value)
            WHERE sp.source = CAST(:target AS source_type)
              AND jsonb_typeof(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') = 'array'
        )
        SELECT DISTINCT c.doi
        FROM candidate_dois c
        {join_clause}
        WHERE c.source IS DISTINCT FROM :target
          AND NOT EXISTS (
                  SELECT 1 FROM staging s WHERE s.source = :target AND s.doi = c.doi
              ){prefix_filter}
          AND NOT EXISTS (SELECT 1 FROM deja_connus k WHERE k.doi = c.doi)
          AND NOT {pending}
        ORDER BY c.doi
    """
    params: dict[str, str] = {"target": target}
    if target_ra:
        params["target_ra"] = target_ra
    rows: ScalarResult[str] = conn.execute(text(query), params).scalars()
    # Re-nettoyage des candidats (idempotent) : `staging.doi` peut porter des DOI non normalisés ; `dict.fromkeys` dédoublonne en préservant l'ordre.
    return list(dict.fromkeys(c for d in rows if (c := clean_doi(d))))
