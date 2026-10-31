"""Lectures des routes `/api/hal-problems/*` : contrôles de qualité HAL des publications (dépôts en double, manques dans les collections, conflits d'affiliation) et comptes HAL multiples par personne."""

from collections import defaultdict
from collections.abc import Iterator, Sequence

from sqlalchemy import Connection, bindparam, text

from domain.normalize import to_plain_text
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.source_records.keys import DISCRIMINANT_TITLE_MIN_LENGTH
from infrastructure.db.source_record_identifiers import source_record_doi_sql
from infrastructure.read_models._common import StructureRef
from infrastructure.read_models.csv_export import MAX_EXPORT_ROWS, csv_chunks
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
from infrastructure.read_models.perimeters.queries import get_persons_structure_ids_list
from infrastructure.read_models.sql_fragments import contributor_display_name
from infrastructure.sql_fragments import usable_identifier

# Identifiants d'une contribution source `sc`, hors identifiants neutralisés.
_HAL_PERSON_ID = usable_identifier("'hal_person_id'")
_ORCID = usable_identifier("'orcid'")
_IDHAL = usable_identifier("'idhal'")
_IDREF = usable_identifier("'idref'")

# Condition sur une attribution d'identifiant `pi` : compte HAL attribué à la personne `pi.person_id`, hors attributions rejetées.
_HAL_ACCOUNT_ATTRIBUTION = (
    f"pi.id_type = '{PersonIdentifierType.HAL_PERSON_ID.value}'"
    f" AND pi.status <> '{AttributionStatus.REJECTED.value}'"
)

# Personnes à au moins deux comptes HAL attribués. Même population pour le comptage et pour la liste.
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
        """Renvoie le détail des publications d'une page et de leurs dépôts HAL, indexé par identifiant.

        Deux requêtes couvrent la page entière, plutôt qu'une par publication : les paires de doublons se comptent par centaines.
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
        # Pour un même `hal_person_id`, le nom et les identifiants des contributions sources HAL sont en principe constants. Des imports de dates différentes divergent parfois ; MIN() retient une valeur déterministe.
        offset = (page - 1) * per_page
        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM ({_PERSONS_WITH_DUPLICATE_HAL_ACCOUNTS}) sub")
        ).one()
        total = total_row.total

        # Détail de chaque compte HAL attribué : contributions sources HAL des contributions de la personne contenant sa référence. Un compte absent de ces contributions a un nom vide et zéro publication.
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
        # Un même DOI déposé sur au moins deux enregistrements sources HAL de la même publication. Les enregistrements sources sans publication sont hors périmètre.
        dup_query = f"""
            FROM (
                SELECT sr.publication_id, sr.source_id, {source_record_doi_sql("sr")} AS doi
                FROM source_records sr
                WHERE sr.source = 'hal' AND sr.publication_id IS NOT NULL
            ) sr
            WHERE sr.doi IS NOT NULL
            GROUP BY sr.publication_id, sr.doi
            HAVING COUNT(*) >= 2
        """

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM (SELECT sr.publication_id {dup_query}) sub")
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT sr.doi,
                       sr.publication_id AS publication_id,
                       array_agg(sr.source_id ORDER BY sr.source_id) AS halids
                {dup_query}
                ORDER BY sr.doi
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
        """Renvoie les structures du périmètre à collection HAL renseignée."""
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
                SELECT DISTINCT p.id, p.title, p.publication_year, p.publication_date,
                       p.doc_type::text AS doc_type, p.doi,
                       (SELECT array_agg(sr2.source_id) FROM source_records sr2
                        WHERE sr2.publication_id = p.id AND sr2.source = 'hal') AS halids
                {base_where}
                ORDER BY p.publication_date DESC, p.id DESC
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
        # Conflit d'affiliation : HAL met la publication dans le périmètre, WoS et OpenAlex, seules sources à donner des adresses, la laissent hors du périmètre.
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
                ORDER BY p.publication_date DESC, p.id DESC
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

    # ── Exports CSV ──────────────────────────────────────────────
    # Chaque export lit sa liste en une seule page, de la taille du plafond commun plus une ligne : la ligne excédentaire signale la coupe.

    def export_duplicate_accounts_csv(self) -> Iterator[str]:
        """Renvoie l'export CSV des comptes auteur HAL en double : une ligne par compte HAL d'une personne."""
        persons, truncated = _capped(
            self.hal_duplicate_accounts(page=1, per_page=_EXPORT_PAGE).persons
        )
        return csv_chunks(
            [
                "Nom",
                "Prénom",
                "RH",
                "Compte HAL",
                "Nom HAL",
                "Publications",
                "idHAL",
                "ORCID",
                "IdRef",
            ],
            (
                [
                    p.last_name,
                    p.first_name,
                    "oui" if p.has_rh else "",
                    a.hal_person_id,
                    a.full_name or "",
                    a.publication_count,
                    a.idhal or "",
                    a.orcid or "",
                    a.idref or "",
                ]
                for p in persons
                for a in p.hal_accounts
            ),
            truncated=truncated,
        )

    def export_duplicate_publications_by_doi_csv(self) -> Iterator[str]:
        """Renvoie l'export CSV des dépôts HAL en double par DOI : une ligne par DOI."""
        pairs, truncated = _capped(
            self.hal_duplicate_publications_by_doi(page=1, per_page=_EXPORT_PAGE).pairs
        )
        return csv_chunks(
            ["DOI", "Année", "Type", "Titre", "Dépôts HAL"],
            (
                [
                    _doi_url(pair.doi),
                    pair.publication.publication_year or "",
                    pair.publication.doc_type or "",
                    to_plain_text(pair.publication.title),
                    " ".join(pair.halids),
                ]
                for pair in pairs
            ),
            truncated=truncated,
        )

    def export_duplicate_publications_by_metadata_csv(self) -> Iterator[str]:
        """Renvoie l'export CSV des doublons possibles par métadonnées : une ligne par paire de publications."""
        pairs, truncated = _capped(
            self.hal_duplicate_publications_by_metadata(page=1, per_page=_EXPORT_PAGE).pairs
        )
        return csv_chunks(
            ["Année", "Type", "Titre A", "Dépôts HAL A", "Titre B", "Dépôts HAL B"],
            (
                [
                    pair.publication_a.publication_year or "",
                    pair.publication_a.doc_type or "",
                    to_plain_text(pair.publication_a.title),
                    " ".join(d.halid for d in pair.publication_a.hal_docs),
                    to_plain_text(pair.publication_b.title),
                    " ".join(d.halid for d in pair.publication_b.hal_docs),
                ]
                for pair in pairs
            ),
            truncated=truncated,
        )

    def export_missing_collections_csv(
        self, *, lab_id: int
    ) -> Iterator[str] | NoMissingCollections:
        """Renvoie l'export CSV des publications du laboratoire absentes de sa collection HAL."""
        result = self.hal_missing_collections(lab_id=lab_id, page=1, per_page=_EXPORT_PAGE)
        if isinstance(result, NoMissingCollections):
            return result
        publications, truncated = _capped(result.publications)
        return csv_chunks(
            ["Année", "Type", "Titre", "DOI", "Dépôts HAL"],
            (
                [
                    p.publication_year or "",
                    p.doc_type or "",
                    to_plain_text(p.title),
                    _doi_url(p.doi),
                    " ".join(p.halids or []),
                ]
                for p in publications
            ),
            truncated=truncated,
        )

    def export_affiliation_conflicts_csv(self) -> Iterator[str]:
        """Renvoie l'export CSV des publications aux affiliations HAL divergentes."""
        publications, truncated = _capped(
            self.hal_affiliation_conflicts(page=1, per_page=_EXPORT_PAGE).publications
        )
        return csv_chunks(
            ["Année", "Type", "Titre", "DOI", "Dépôts HAL", "Laboratoires"],
            (
                [
                    p.publication_year or "",
                    p.doc_type or "",
                    to_plain_text(p.title),
                    _doi_url(p.doi),
                    " ".join(p.halids or []),
                    ", ".join(lab.acronym or lab.name for lab in p.laboratories),
                ]
                for p in publications
            ),
            truncated=truncated,
        )


# Taille de la page unique d'un export.
_EXPORT_PAGE = MAX_EXPORT_ROWS + 1


def _capped[T](items: Sequence[T]) -> tuple[Sequence[T], bool]:
    """Renvoie les éléments ramenés au plafond des exports, et si la coupe a eu lieu."""
    return items[:MAX_EXPORT_ROWS], len(items) > MAX_EXPORT_ROWS


def _doi_url(doi: str | None) -> str:
    return f"https://doi.org/{doi}" if doi else ""
