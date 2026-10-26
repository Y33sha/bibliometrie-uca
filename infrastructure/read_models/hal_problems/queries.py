"""Query services pour le router `/api/hal-problems/*`.

Contrôles qualité HAL au niveau des publications (doublons de dépôts, manques dans les collections, conflits d'affiliation) + comptes HAL multiples par personne.
"""

from collections import defaultdict

from sqlalchemy import Connection, bindparam, text

from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.source_records.keys import DISCRIMINANT_TITLE_MIN_LENGTH
from infrastructure.read_models._common import StructureRef
from infrastructure.read_models.hal_problems.models import (
    HalAccountSummary,
    HalAffiliationConflictPublication,
    HalAffiliationConflictsResponse,
    HalCollectionLab,
    HalDocSummary,
    HalDoiDuplicatePair,
    HalDoiDuplicatesResponse,
    HalDuplicateAccountPerson,
    HalDuplicateAccountsResponse,
    HalMetaDuplicatePair,
    HalMetaDuplicatesResponse,
    HalMissingCollectionPublication,
    HalMissingCollectionsResponse,
    HalPublicationDetail,
    NoMissingCollections,
)
from infrastructure.read_models.perimeters.queries import (
    get_persons_perimeter_root_ids,
    get_persons_structure_ids_list,
)
from infrastructure.read_models.sql_fragments import contributor_display_name
from infrastructure.sql_fragments import usable_identifier

# Identifiants d'une contribution source `sc`, hors ceux qu'elle neutralise.
_HAL_PERSON_ID = usable_identifier("'hal_person_id'")
_ORCID = usable_identifier("'orcid'")
_IDHAL = usable_identifier("'idhal'")
_IDREF = usable_identifier("'idref'")

# Condition sur une attribution d'identifiant `pi` : compte HAL attribué à la personne `pi.person_id`, hors attributions rejetées.
_HAL_ACCOUNT_ATTRIBUTION = (
    f"pi.id_type = '{PersonIdentifierType.HAL_PERSON_ID.value}'"
    f" AND pi.status <> '{AttributionStatus.REJECTED.value}'"
)

# Personnes auxquelles au moins deux comptes HAL sont attribués : l'anomalie que la page recense, et la même population pour le comptage comme pour la liste.
_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS = f"""
    SELECT pi.person_id
    FROM person_identifiers pi
    WHERE {_HAL_ACCOUNT_ATTRIBUTION}
    GROUP BY pi.person_id
    HAVING COUNT(*) >= 2
"""


class HalProblemsQueries:
    """Lectures pour /api/hal-problems/*."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _hal_publication_details(
        self, publication_ids: list[int]
    ) -> dict[int, HalPublicationDetail]:
        """Détail des publications d'une page et de leurs dépôts HAL, indexé par identifiant.

        Deux requêtes pour la page entière : les paires de doublons se comptent par centaines, et une lecture par publication en ferait autant d'allers-retours.
        """
        if not publication_ids:
            return {}
        publication_rows = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.publication_year, p.doc_type::text AS doc_type,
                       p.doi, p.container_title
                FROM publications p WHERE p.id = ANY(:pids)
            """).bindparams(bindparam("pids")),
            {"pids": publication_ids},
        ).all()
        hal_rows = self._conn.execute(
            text("""
                SELECT sr.publication_id, sr.source_id AS halid, sr.hal_collections,
                       sr.doc_type AS hal_doc_type,
                       sr.publication_year AS hal_publication_year, sr.title AS hal_title,
                       (SELECT COUNT(*) FROM source_contributions sc2
                        WHERE sc2.source = 'hal' AND sc2.source_record_id = sr.id) AS author_count
                FROM source_records sr
                WHERE sr.publication_id = ANY(:pids) AND sr.source = 'hal'
                ORDER BY sr.source_id
            """).bindparams(bindparam("pids")),
            {"pids": publication_ids},
        ).all()

        docs_by_publication: dict[int, list[HalDocSummary]] = defaultdict(list)
        for r in hal_rows:
            docs_by_publication[r.publication_id].append(
                HalDocSummary(
                    halid=r.halid,
                    hal_collections=list(r.hal_collections) if r.hal_collections else None,
                    hal_doc_type=r.hal_doc_type,
                    hal_publication_year=r.hal_publication_year,
                    hal_title=r.hal_title,
                    author_count=r.author_count,
                )
            )
        return {
            r.id: HalPublicationDetail(
                id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doc_type=r.doc_type,
                doi=r.doi,
                container_title=r.container_title,
                hal_docs=docs_by_publication[r.id],
            )
            for r in publication_rows
        }

    def hal_duplicate_accounts(self, *, page: int, per_page: int) -> HalDuplicateAccountsResponse:
        # Note sur les agrégats MIN() ci-dessous : pour un même `hal_person_id`, les valeurs de `raw_author_name`/`orcid`/`idhal`/`idref` observées sur les `source_contributions` HAL devraient être constantes (ces champs sont attachés au compte HAL, et non à la contribution source). En théorie aucune variation possible. En pratique, si des imports à des dates différentes ont posé des valeurs divergentes (avant que la comparaison de hash ne réimporte les payloads obsolètes), MIN() ramasse une valeur déterministe arbitraire. L'optimal aurait été MAX(created_at), mais `source_contributions` n'a pas de `created_at`.
        offset = (page - 1) * per_page
        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM ({_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS}) sub")
        ).one()
        total = total_row.total

        # Chaque compte HAL attribué se détaille par les contributions sources HAL des contributions de la personne qui contiennent sa référence. Un compte absent de ces contributions a un nom vide et zéro publication.
        rows = self._conn.execute(
            text(f"""
                WITH page_persons AS MATERIALIZED (
                    SELECT p.id, p.last_name, p.first_name, (prh.id IS NOT NULL) AS has_rh
                    FROM persons p
                    LEFT JOIN hr_records prh ON prh.person_id = p.id
                    WHERE p.id IN ({_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS})
                    ORDER BY LOWER(p.last_name), LOWER(p.first_name)
                    LIMIT :pg_limit OFFSET :pg_offset
                ),
                hal_accounts AS (
                    SELECT pi.person_id, pi.id_value::int AS hal_person_id, s.*
                    FROM person_identifiers pi
                    CROSS JOIN LATERAL (
                        SELECT
                            MIN({contributor_display_name()}) AS full_name,
                            MIN({_ORCID}) AS orcid,
                            MIN({_IDHAL}) AS idhal,
                            MIN({_IDREF}) AS idref,
                            COUNT(*) AS publication_count
                        FROM contributions g
                        JOIN aligned_source_contributions m ON m.contribution_id = g.id
                        JOIN source_contributions sc ON sc.id = m.source_contribution_id
                        JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                        WHERE g.person_id = pi.person_id
                          AND sc.source = 'hal'
                          AND {_HAL_PERSON_ID} = pi.id_value
                    ) s
                    WHERE {_HAL_ACCOUNT_ATTRIBUTION}
                      AND pi.person_id IN (SELECT id FROM page_persons)
                )
                SELECT pp.id AS person_id, pp.last_name, pp.first_name, pp.has_rh,
                       (SELECT json_agg(json_build_object(
                           'hal_person_id', ha.hal_person_id,
                           'full_name', ha.full_name,
                           'idhal', ha.idhal,
                           'orcid', ha.orcid,
                           'idref', ha.idref,
                           'publication_count', ha.publication_count
                       ) ORDER BY ha.hal_person_id)
                        FROM hal_accounts ha WHERE ha.person_id = pp.id
                       ) AS hal_accounts
                FROM page_persons pp
                ORDER BY LOWER(pp.last_name), LOWER(pp.first_name)
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

    def hal_duplicate_publications_by_doi(
        self, *, page: int, per_page: int
    ) -> HalDoiDuplicatesResponse:
        offset = (page - 1) * per_page
        # Un même DOI (insensible à la casse) déposé sur au moins deux enregistrements sources HAL de la même publication. Les enregistrements sans publication sont hors périmètre.
        dup_query = """
            FROM source_records sr
            WHERE sr.source = 'hal' AND sr.publication_id IS NOT NULL
              AND sr.doi IS NOT NULL AND sr.doi != ''
            GROUP BY sr.publication_id, LOWER(sr.doi)
            HAVING COUNT(*) >= 2
        """

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM (SELECT sr.publication_id {dup_query}) sub")
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT LOWER(sr.doi) AS doi,
                       sr.publication_id AS publication_id,
                       array_agg(sr.source_id ORDER BY sr.source_id) AS halids
                {dup_query}
                ORDER BY LOWER(sr.doi)
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pg_limit": per_page, "pg_offset": offset},
        ).all()
        details = self._hal_publication_details([r.publication_id for r in rows])
        pairs = [
            HalDoiDuplicatePair(
                doi=r.doi, halids=list(r.halids), publication=details[r.publication_id]
            )
            for r in rows
        ]

        return HalDoiDuplicatesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pairs=pairs,
        )

    def hal_duplicate_publications_by_metadata(
        self, *, page: int, per_page: int
    ) -> HalMetaDuplicatesResponse:
        offset = (page - 1) * per_page
        dup_query = f"""
            FROM publications p1
            JOIN publications p2
              ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            JOIN source_records hd1
              ON hd1.publication_id = p1.id AND hd1.source = 'hal'
            JOIN source_records hd2
              ON hd2.publication_id = p2.id AND hd2.source = 'hal'
            WHERE LENGTH(p1.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
              AND p1.publication_year = p2.publication_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL
                       AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM source_contributions sc1
                   WHERE sc1.source = 'hal' AND sc1.source_record_id = hd1.id)
                  - (SELECT COUNT(*) FROM source_contributions sc2
                     WHERE sc2.source = 'hal' AND sc2.source_record_id = hd2.id)
              ) <= 2
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
        details = self._hal_publication_details([r.id_a for r in rows] + [r.id_b for r in rows])
        pairs = [
            HalMetaDuplicatePair(publication_a=details[r.id_a], publication_b=details[r.id_b])
            for r in rows
        ]

        return HalMetaDuplicatesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pairs=pairs,
        )

    def hal_missing_collections_labs(self) -> list[HalCollectionLab]:
        """Structures du périmètre dont une collection HAL est renseignée — celles dont la collection se compare.

        Sans collection, la question « que manque-t-il à sa collection ? » est sans objet.
        """
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.acronym, s.name, s.hal_collection
                FROM structures s
                WHERE s.hal_collection IS NOT NULL
                  AND s.id = ANY(:perimeter_ids)
                ORDER BY s.acronym
            """),
            {"perimeter_ids": get_persons_structure_ids_list(self._conn)},
        ).all()
        return [
            HalCollectionLab(
                id=r.id, acronym=r.acronym, name=r.name, hal_collection=r.hal_collection
            )
            for r in rows
        ]

    def _perimeter_root_collections(self) -> list[str]:
        """Collections HAL des structures racines du périmètre — celles de l'établissement.

        Une racine sans collection n'en fournit aucune ; plusieurs racines fournissent chacune la sienne.
        """
        rows = self._conn.execute(
            text("""
                SELECT s.hal_collection FROM structures s
                WHERE s.id = ANY(:ids) AND s.hal_collection IS NOT NULL
            """),
            {"ids": get_persons_perimeter_root_ids(self._conn)},
        ).all()
        return [r.hal_collection for r in rows]

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
        binds: dict[str, object] = {
            "lab_arr": [lab_id],
            "col": col,
            "root_cols": self._perimeter_root_collections(),
            "pg_limit": per_page,
            "pg_offset": offset,
        }

        base_where = """
            FROM publications p
            JOIN contributions a ON a.publication_id = p.id
            WHERE EXISTS (SELECT 1 FROM contribution_structures aus
                          WHERE aus.contribution_id = a.id
                            AND aus.structure_id = ANY(:lab_arr))
              AND EXISTS (SELECT 1 FROM source_records sr
                          WHERE sr.publication_id = p.id AND sr.source = 'hal')
              AND NOT EXISTS (SELECT 1 FROM source_records sr
                              WHERE sr.publication_id = p.id AND sr.source = 'hal'
                                AND :col = ANY(sr.hal_collections))
        """

        total_row = self._conn.execute(
            text(f"SELECT COUNT(DISTINCT p.id) AS total {base_where}"), binds
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT p.id, p.title, p.publication_year, p.doc_type::text AS doc_type,
                       p.doi,
                       (SELECT array_agg(sr2.source_id) FROM source_records sr2
                        WHERE sr2.publication_id = p.id AND sr2.source = 'hal') AS halids,
                       NOT EXISTS (SELECT 1 FROM source_records sr2
                                   WHERE sr2.publication_id = p.id AND sr2.source = 'hal'
                                     AND sr2.hal_collections && :root_cols
                                  ) AS outside_perimeter_collections
                {base_where}
                ORDER BY p.publication_year DESC NULLS LAST, p.id DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            binds,
        ).all()
        publications = [
            HalMissingCollectionPublication(
                id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doc_type=r.doc_type,
                doi=r.doi,
                halids=list(r.halids) if r.halids else None,
                outside_perimeter_collections=r.outside_perimeter_collections,
            )
            for r in rows
        ]

        return HalMissingCollectionsResponse(
            total=total,
            page=page,
            per_page=per_page,
            lab_acronym=lab_row.acronym,
            hal_collection=col,
            publications=publications,
        )

    def hal_affiliation_conflicts(
        self, *, page: int, per_page: int
    ) -> HalAffiliationConflictsResponse:
        offset = (page - 1) * per_page
        # Conflit d'affiliation : HAL classe la publication in_perimeter, WoS/OpenAlex (seules à donner des adresses) non.
        base_cte = """
        WITH hal_in_perimeter_pubs AS (
            SELECT DISTINCT sr.publication_id
            FROM source_records sr
            JOIN source_contributions sc ON sc.source_record_id = sr.id
            WHERE sr.source = 'hal'
              AND sc.in_perimeter = TRUE
              AND sr.publication_id IS NOT NULL
        ),
        conflict_pubs AS (
            SELECT h.publication_id
            FROM hal_in_perimeter_pubs h
            WHERE NOT EXISTS (
                SELECT 1 FROM source_records sr
                JOIN source_contributions sc ON sc.source_record_id = sr.id
                WHERE sr.publication_id = h.publication_id
                  AND sr.source IN ('wos', 'openalex')
                  AND sc.in_perimeter = TRUE
            )
            AND EXISTS (
                SELECT 1 FROM source_records sr
                JOIN source_contributions sc ON sc.source_record_id = sr.id
                JOIN source_contribution_addresses sca ON sca.source_contribution_id = sc.id
                WHERE sr.publication_id = h.publication_id
                  AND sr.source IN ('wos', 'openalex')
            )
        )
        """

        total_row = self._conn.execute(
            text(f"{base_cte} SELECT COUNT(*) AS n FROM conflict_pubs")
        ).one()
        total = total_row.n

        rows = self._conn.execute(
            text(f"""
                {base_cte}
                SELECT p.id, p.title, p.publication_year, p.doc_type::text AS doc_type, p.doi,
                       (SELECT array_agg(sr2.source_id) FROM source_records sr2
                        WHERE sr2.publication_id = p.id AND sr2.source = 'hal') AS halids,
                       (SELECT json_agg(json_build_object('acronym', l.acronym, 'name', l.name)
                                        ORDER BY COALESCE(l.acronym, l.name))
                        FROM (SELECT DISTINCT s.acronym, s.name
                              FROM contributions a2
                              JOIN contribution_structures aus2 ON aus2.contribution_id = a2.id
                              JOIN structures s ON s.id = aus2.structure_id
                              WHERE a2.publication_id = p.id
                                AND a2.in_perimeter = TRUE
                                AND s.hal_collection IS NOT NULL
                                AND s.id = ANY(:perimeter_ids)) l
                       ) AS laboratories
                FROM conflict_pubs cp
                JOIN publications p ON p.id = cp.publication_id
                ORDER BY p.publication_year DESC NULLS LAST, p.id DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {
                "pg_limit": per_page,
                "pg_offset": offset,
                "perimeter_ids": get_persons_structure_ids_list(self._conn),
            },
        ).all()
        publications = [
            HalAffiliationConflictPublication(
                id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doc_type=r.doc_type,
                doi=r.doi,
                halids=list(r.halids) if r.halids else None,
                laboratories=[StructureRef.model_validate(x) for x in (r.laboratories or [])],
            )
            for r in rows
        ]

        return HalAffiliationConflictsResponse(
            total=total,
            page=page,
            per_page=per_page,
            publications=publications,
        )
