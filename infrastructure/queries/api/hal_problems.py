"""Query services pour le router `/api/hal-problems/*`.

Contrôles qualité HAL au niveau des publications (doublons de dépôts, manques dans les collections, conflits d'affiliation) + comptes HAL multiples par personne. `PgHalProblemsQueries` hérite explicitement du Protocol `application.ports.api.hal_problems_queries.HalProblemsQueries`.
"""

from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, bindparam, text

from application.ports.api.hal_problems_queries import (
    HalAccountSummary,
    HalAffiliationConflictPub,
    HalAffiliationConflictsResponse,
    HalCollectionLab,
    HalDocSummary,
    HalDoiDuplicatePair,
    HalDoiDuplicatesResponse,
    HalDuplicateAccountPerson,
    HalDuplicateAccountsResponse,
    HalMetaDuplicatePair,
    HalMetaDuplicatesResponse,
    HalMissingCollectionPub,
    HalMissingCollectionsResponse,
    HalProblemsQueries,
    HalPubDetail,
    NoMissingCollections,
)
from domain.source_publications.keys import DISCRIMINANT_TITLE_MIN_LENGTH

# Signatures HAL rattachées à une personne et portant la référence d'un compte HAL.
_HAL_ACCOUNT_SIGNATURES = """
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE sa.source = 'hal'
      AND sa.person_id IS NOT NULL
      AND aik.person_identifiers->>'hal_person_id' IS NOT NULL
"""

# Personnes portant au moins deux comptes HAL distincts : l'anomalie que la page recense, et
# la même population pour le comptage comme pour la liste.
_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS = f"""
    SELECT sa.person_id
    {_HAL_ACCOUNT_SIGNATURES}
    GROUP BY sa.person_id
    HAVING COUNT(DISTINCT aik.person_identifiers->>'hal_person_id') >= 2
"""


class PgHalProblemsQueries(HalProblemsQueries):
    """Adapter SA pour `HalProblemsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _hal_pub_details(self, pub_ids: list[int]) -> dict[int, HalPubDetail]:
        """Détail des publications d'une page et de leurs dépôts HAL, indexé par identifiant.

        Deux requêtes pour la page entière : les paires de doublons se comptent par centaines, et une lecture par publication en ferait autant d'allers-retours.
        """
        if not pub_ids:
            return {}
        pub_rows = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type,
                       p.doi, p.container_title
                FROM publications p WHERE p.id = ANY(:pids)
            """).bindparams(bindparam("pids")),
            {"pids": pub_ids},
        ).all()
        hal_rows = self._conn.execute(
            text("""
                SELECT sd.publication_id, sd.source_id AS halid, sd.hal_collections,
                       sd.doc_type AS hal_doc_type,
                       sd.pub_year AS hal_pub_year, sd.title AS hal_title,
                       (SELECT COUNT(*) FROM source_authorships sa2
                        WHERE sa2.source = 'hal' AND sa2.source_publication_id = sd.id) AS author_count
                FROM source_publications sd
                WHERE sd.publication_id = ANY(:pids) AND sd.source = 'hal'
                ORDER BY sd.source_id
            """).bindparams(bindparam("pids")),
            {"pids": pub_ids},
        ).all()

        docs_by_pub: dict[int, list[HalDocSummary]] = defaultdict(list)
        for r in hal_rows:
            docs_by_pub[r.publication_id].append(
                HalDocSummary(
                    halid=r.halid,
                    hal_collections=list(r.hal_collections) if r.hal_collections else None,
                    hal_doc_type=r.hal_doc_type,
                    hal_pub_year=r.hal_pub_year,
                    hal_title=r.hal_title,
                    author_count=r.author_count,
                )
            )
        return {
            r.id: HalPubDetail(
                id=r.id,
                title=r.title,
                pub_year=r.pub_year,
                doc_type=r.doc_type,
                doi=r.doi,
                container_title=r.container_title,
                hal_docs=docs_by_pub[r.id],
            )
            for r in pub_rows
        }

    def hal_duplicate_accounts(self, *, page: int, per_page: int) -> HalDuplicateAccountsResponse:
        # Note sur les agrégats MIN() ci-dessous : pour un même `hal_person_id`, les valeurs de `raw_author_name`/`orcid`/`idhal`/`idref` observées sur les `source_authorships` HAL devraient être constantes (ces champs sont attachés au compte HAL, pas à la signature). En théorie aucune variation possible. En pratique, si des imports à des dates différentes ont posé des valeurs divergentes (avant que la comparaison de hash ne réimporte les payloads obsolètes), MIN() ramasse une valeur déterministe arbitraire. L'optimal aurait été MAX(created_at), mais `source_authorships` n'a pas de `created_at`.
        offset = (page - 1) * per_page
        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM ({_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS}) sub")
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                WITH hal_accounts AS (
                    SELECT
                        sa.person_id,
                        (aik.person_identifiers->>'hal_person_id')::int AS hal_person_id,
                        MIN(sa.raw_author_name) AS full_name,
                        MIN(aik.person_identifiers->>'orcid') AS orcid,
                        MIN(aik.person_identifiers->>'idhal') AS idhal,
                        MIN(aik.person_identifiers->>'idref') AS idref,
                        COUNT(*) AS pub_count
                    {_HAL_ACCOUNT_SIGNATURES}
                    GROUP BY sa.person_id, aik.person_identifiers->>'hal_person_id'
                )
                SELECT p.id AS person_id, p.last_name, p.first_name,
                       (prh.id IS NOT NULL) AS has_rh,
                       (SELECT json_agg(json_build_object(
                           'hal_person_id', ha.hal_person_id,
                           'full_name', ha.full_name,
                           'idhal', ha.idhal,
                           'orcid', ha.orcid,
                           'idref', ha.idref,
                           'pub_count', ha.pub_count
                       ) ORDER BY ha.hal_person_id)
                        FROM hal_accounts ha WHERE ha.person_id = p.id
                       ) AS hal_accounts
                FROM persons p
                LEFT JOIN persons_rh prh ON prh.person_id = p.id
                WHERE p.id IN ({_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS})
                ORDER BY LOWER(p.last_name), LOWER(p.first_name)
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pg_limit": per_page, "pg_offset": offset},
        ).all()
        persons = [
            HalDuplicateAccountPerson(
                person_id=r.person_id,
                last_name=r.last_name,
                first_name=r.first_name,
                has_rh=r.has_rh,
                hal_accounts=[HalAccountSummary(**acc) for acc in (r.hal_accounts or [])],
            )
            for r in rows
        ]

        return HalDuplicateAccountsResponse(
            total=total,
            page=page,
            per_page=per_page,
            persons=persons,
        )

    def hal_duplicate_pubs_by_doi(self, *, page: int, per_page: int) -> HalDoiDuplicatesResponse:
        offset = (page - 1) * per_page
        total_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS total FROM (
                    SELECT sd.publication_id, LOWER(sd.doi)
                    FROM source_publications sd
                    WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
                    GROUP BY sd.publication_id, LOWER(sd.doi)
                    HAVING COUNT(*) >= 2
                ) sub
            """)
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text("""
                SELECT LOWER(sd.doi) AS doi,
                       sd.publication_id AS pub_id,
                       array_agg(sd.source_id ORDER BY sd.source_id) AS halids
                FROM source_publications sd
                WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
                GROUP BY sd.publication_id, LOWER(sd.doi)
                HAVING COUNT(*) >= 2
                ORDER BY LOWER(sd.doi)
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pg_limit": per_page, "pg_offset": offset},
        ).all()
        details = self._hal_pub_details([r.pub_id for r in rows])
        pairs = [
            HalDoiDuplicatePair(doi=r.doi, halids=list(r.halids), publication=details[r.pub_id])
            for r in rows
        ]

        return HalDoiDuplicatesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pairs=pairs,
        )

    def hal_duplicate_pubs_by_metadata(
        self, *, page: int, per_page: int
    ) -> HalMetaDuplicatesResponse:
        offset = (page - 1) * per_page
        dup_query = f"""
            FROM publications p1
            JOIN publications p2
              ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            JOIN source_publications hd1
              ON hd1.publication_id = p1.id AND hd1.source = 'hal'
            JOIN source_publications hd2
              ON hd2.publication_id = p2.id AND hd2.source = 'hal'
            WHERE LENGTH(p1.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
              AND p1.pub_year = p2.pub_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL
                       AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM source_authorships sa1
                   WHERE sa1.source = 'hal' AND sa1.source_publication_id = hd1.id)
                  - (SELECT COUNT(*) FROM source_authorships sa2
                     WHERE sa2.source = 'hal' AND sa2.source_publication_id = hd2.id)
              ) <= 2
              AND NOT EXISTS (SELECT 1 FROM distinct_publications dp
                              WHERE dp.pub_id_a = LEAST(p1.id, p2.id)
                                AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        total_row = self._conn.execute(text(f"SELECT COUNT(*) AS total {dup_query}")).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT p1.id AS id_a, p2.id AS id_b
                {dup_query}
                ORDER BY p1.id
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pg_limit": per_page, "pg_offset": offset},
        ).all()
        details = self._hal_pub_details([r.id_a for r in rows] + [r.id_b for r in rows])
        pairs = [HalMetaDuplicatePair(pub_a=details[r.id_a], pub_b=details[r.id_b]) for r in rows]

        return HalMetaDuplicatesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pairs=pairs,
        )

    def hal_missing_collections_labs(self) -> list[HalCollectionLab]:
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.acronym, s.name, s.hal_collection
                FROM structures s
                WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
                ORDER BY s.acronym
            """)
        ).all()
        return [
            HalCollectionLab(
                id=r.id, acronym=r.acronym, name=r.name, hal_collection=r.hal_collection
            )
            for r in rows
        ]

    def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> HalMissingCollectionsResponse | NoMissingCollections:
        lab_row = self._conn.execute(
            text("SELECT acronym, hal_collection FROM structures WHERE id = :id"),
            {"id": lab_id},
        ).one_or_none()
        if not lab_row:
            return NoMissingCollections.UNKNOWN_LAB
        if not lab_row.hal_collection:
            return NoMissingCollections.NO_COLLECTION

        offset = (page - 1) * per_page
        col = lab_row.hal_collection
        binds: dict[str, Any] = {
            "lab_arr": [lab_id],
            "col": col,
            "pg_limit": per_page,
            "pg_offset": offset,
        }

        base_where = """
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id
            WHERE EXISTS (SELECT 1 FROM authorship_structures aus
                          WHERE aus.authorship_id = a.id
                            AND aus.structure_id = ANY(:lab_arr))
              AND EXISTS (SELECT 1 FROM source_publications sd
                          WHERE sd.publication_id = p.id AND sd.source = 'hal')
              AND NOT EXISTS (SELECT 1 FROM source_publications sd
                              WHERE sd.publication_id = p.id AND sd.source = 'hal'
                                AND :col = ANY(sd.hal_collections))
        """

        total_row = self._conn.execute(
            text(f"SELECT COUNT(DISTINCT p.id) AS total {base_where}"), binds
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type,
                       p.doi,
                       (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                        WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                       NOT EXISTS (SELECT 1 FROM source_publications sd2
                                   WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
                                     AND 'PRES_CLERMONT' = ANY(sd2.hal_collections)) AS hors_uca
                {base_where}
                ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            binds,
        ).all()
        pubs = [
            HalMissingCollectionPub(
                id=r.id,
                title=r.title,
                pub_year=r.pub_year,
                doc_type=r.doc_type,
                doi=r.doi,
                halids=list(r.halids) if r.halids else None,
                hors_uca=r.hors_uca,
            )
            for r in rows
        ]

        return HalMissingCollectionsResponse(
            total=total,
            page=page,
            per_page=per_page,
            lab_acronym=lab_row.acronym,
            hal_collection=col,
            publications=pubs,
        )

    def hal_affiliation_conflicts(
        self, *, page: int, per_page: int
    ) -> HalAffiliationConflictsResponse:
        offset = (page - 1) * per_page
        # Publications dont :
        #  1. au moins une source_publication HAL a au moins une authorship in_perimeter ;
        #  2. au moins une source_publication WoS/OA a au moins une authorship
        #     avec une adresse (= la source a effectivement examiné
        #     l'affiliation — garde-fou contre les faux positifs sur les SPs
        #     sans données d'adresse, qui restent in_perimeter=FALSE par
        #     défaut sans signal métier) ;
        #  3. aucune authorship d'une source_publication WoS/OA n'est in_perimeter.
        # Sources comparées limitées à WoS et OpenAlex : ScanR moissonne HAL et
        # reproduit ses affiliations (donc non informatif), theses n'arbitre
        # pas une publi standard, crossref n'a pas d'adresses.
        #
        # Implémentation : on agrège d'abord par SP WoS/OA les drapeaux
        # `any_addressed` et `any_uca`, puis on regroupe par publication
        # canonique avant de filtrer (agg AS / sur les EXISTS imbriqués
        # qui forçaient un Hash Join sur les 11M source_authorships).
        # Exploite l'index partiel `idx_sa_in_perimeter`.
        base_cte = """
        WITH wos_oa_sps AS (
            SELECT id, publication_id
            FROM source_publications
            WHERE source IN ('wos', 'openalex')
              AND publication_id IS NOT NULL
        ),
        wos_oa_pub_summary AS (
            SELECT
                sps.publication_id,
                bool_or(EXISTS (
                    SELECT 1 FROM source_authorship_addresses saa
                    JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                    WHERE sa.source_publication_id = sps.id
                )) AS any_addressed,
                bool_or(EXISTS (
                    SELECT 1 FROM source_authorships sa
                    WHERE sa.source_publication_id = sps.id
                      AND sa.in_perimeter = TRUE
                )) AS any_uca
            FROM wos_oa_sps sps
            GROUP BY sps.publication_id
        ),
        hal_uca_pubs AS (
            SELECT DISTINCT sp.publication_id
            FROM source_publications sp
            JOIN source_authorships sa ON sa.source_publication_id = sp.id
            WHERE sp.source = 'hal'
              AND sa.in_perimeter = TRUE
              AND sp.publication_id IS NOT NULL
        ),
        conflict_pubs AS (
            SELECT h.publication_id
            FROM hal_uca_pubs h
            JOIN wos_oa_pub_summary s ON s.publication_id = h.publication_id
            WHERE s.any_addressed AND NOT s.any_uca
        )
        """

        total_row = self._conn.execute(
            text(f"{base_cte} SELECT COUNT(*) AS n FROM conflict_pubs")
        ).one()
        total = total_row.n

        rows = self._conn.execute(
            text(f"""
                {base_cte}
                SELECT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type, p.doi,
                       (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                        WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                       (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                        FROM authorships a2
                        JOIN authorship_structures aus2 ON aus2.authorship_id = a2.id
                        JOIN structures s ON s.id = aus2.structure_id
                        WHERE a2.publication_id = p.id
                          AND a2.in_perimeter = TRUE
                          AND s.structure_type = 'labo') AS labs
                FROM conflict_pubs cp
                JOIN publications p ON p.id = cp.publication_id
                ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pg_limit": per_page, "pg_offset": offset},
        ).all()
        pubs = [
            HalAffiliationConflictPub(
                id=r.id,
                title=r.title,
                pub_year=r.pub_year,
                doc_type=r.doc_type,
                doi=r.doi,
                halids=list(r.halids) if r.halids else None,
                labs=r.labs,
            )
            for r in rows
        ]

        return HalAffiliationConflictsResponse(
            total=total,
            page=page,
            per_page=per_page,
            publications=pubs,
        )
