"""Query services pour `/api/addresses/*`."""

from dataclasses import replace

from sqlalchemy import Connection, text

from application.ports.repositories.address_repository import AddressCountryFilter
from domain.types import JsonValue
from infrastructure.read_models._common import FacetOption
from infrastructure.read_models.addresses.models import (
    AddressesCountriesResponse,
    AddressForCountryAttribution,
    AddressListFilters,
    AddressListResponse,
    AddressOut,
    AddressPublicationItem,
    AddressStatsResponse,
    AddressStructureSummary,
    FoundCountry,
    StructureLinkState,
)
from infrastructure.read_models.sql_fragments import contributor_display_name
from infrastructure.sql_fragments import address_country_conditions

# « Reconnue » comme une structure = lien pending (détecté, non revu) ou confirmé ; exclut le rejeté (is_confirmed = FALSE) et l'absence de lien. Utilisé par les prédicats Structure de `list_addresses`.
_RECOGNIZED_LINK = (
    "((asx.matched_form_id IS NOT NULL AND asx.is_confirmed IS NULL) OR asx.is_confirmed = TRUE)"
)


def _countries_where(filters: AddressCountryFilter) -> tuple[str, dict[str, object]]:
    """Clause WHERE de la liste des adresses à attribuer et de ses facettes. Une facette retire de `filters` sa propre dimension : ses comptes sont exclusifs."""
    conditions, binds = address_country_conditions(filters)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where, binds


def address_structures_json(addr_ref: str) -> str:
    """Projection JSON des structures liées à une adresse, au format `AddressStructureSummary`.

    `addr_ref` est l'expression SQL désignant l'id d'adresse : `a.id` en sous-requête corrélée d'une liste, `:id` en requête autonome.
    """
    return f"""
        SELECT json_agg(json_build_object(
                   'id', s.id, 'name', s.name, 'acronym', s.acronym,
                   'is_confirmed', ast2.is_confirmed,
                   'is_detected', (ast2.matched_form_id IS NOT NULL)
               ) ORDER BY COALESCE(s.acronym, s.name))
        FROM address_structures ast2
        JOIN structures s ON s.id = ast2.structure_id
        WHERE ast2.address_id = {addr_ref}
    """


class AddressesQueries:
    """Lectures sur les adresses."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_addresses(
        self,
        *,
        structure_id: int,
        filters: AddressListFilters,
        page: int,
        per_page: int,
    ) -> AddressListResponse:
        """Liste paginée des adresses avec filtres détection/validation."""
        offset = (page - 1) * per_page
        use_inner_join = filters.detected == "yes"

        parts: list[str] = []
        binds: dict[str, object] = {"sid": structure_id}

        if filters.detected == "yes":
            parts.append("ast_filter.matched_form_id IS NOT NULL")
        elif filters.detected == "no":
            parts.append("(ast_filter.id IS NULL OR ast_filter.matched_form_id IS NULL)")

        if filters.validation == "pending":
            if use_inner_join:
                parts.append("ast_filter.is_confirmed IS NULL")
            else:
                parts.append("(ast_filter.id IS NULL OR ast_filter.is_confirmed IS NULL)")
        elif filters.validation == "confirmed":
            parts.append("ast_filter.is_confirmed = TRUE")
        elif filters.validation == "rejected":
            parts.append("ast_filter.is_confirmed = FALSE")

        for i, tp in enumerate(filters.text_predicates):
            if not tp.term:
                continue
            op = "NOT ILIKE" if tp.mode == "not_contains" else "ILIKE"
            bind = f"txt{i}"
            parts.append(f"unaccent(a.raw_text) {op} unaccent(:{bind})")
            binds[bind] = f"%{tp.term}%"

        for i, source_record in enumerate(filters.structure_predicates):
            if not source_record.structure_ids:
                continue
            bind = f"sids{i}"
            binds[bind] = list(source_record.structure_ids)
            exists = (
                "EXISTS (SELECT 1 FROM address_structures asx "
                f"WHERE asx.address_id = a.id AND asx.structure_id = ANY(:{bind}) "
                f"AND {_RECOGNIZED_LINK})"
            )
            # recognized = reconnue comme au moins une des structures (OR) ; not_recognized = reconnue comme aucune (De Morgan → NOT EXISTS).
            parts.append(exists if source_record.operator == "recognized" else f"NOT {exists}")

        where_clause = (" AND " + " AND ".join(parts)) if parts else ""
        join_type = "JOIN" if use_inner_join else "LEFT JOIN"

        from_clause = f"""
            FROM addresses a
            {join_type} address_structures ast_filter
                ON ast_filter.address_id = a.id AND ast_filter.structure_id = :sid
            WHERE TRUE {where_clause}
        """

        total_row = self._conn.execute(text(f"SELECT COUNT(*) AS total {from_clause}"), binds).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT a.id, a.raw_text, a.publication_count,
                       ast_filter.is_confirmed,
                       (ast_filter.matched_form_id IS NOT NULL) AS is_detected,
                       ({address_structures_json("a.id")}) AS structures
                {from_clause}
                ORDER BY a.publication_count DESC, a.id
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()

        addresses = [
            AddressOut(
                id=r.id,
                raw_text=r.raw_text,
                is_confirmed=r.is_confirmed,
                is_detected=r.is_detected or False,
                structures=[
                    AddressStructureSummary.model_validate(s) for s in (r.structures or [])
                ],
                publication_count=r.publication_count,
            )
            for r in rows
        ]

        return AddressListResponse(
            total=total,
            page=page,
            per_page=per_page,
            addresses=addresses,
        )

    def address_exists(self, addr_id: int) -> bool:
        row = self._conn.execute(
            text("SELECT 1 FROM addresses WHERE id = :id"), {"id": addr_id}
        ).one_or_none()
        return row is not None

    def get_address_raw_text(self, addr_id: int) -> str | None:
        """Texte brut de l'adresse ; `None` signale une adresse absente, la colonne étant obligatoire."""
        row = self._conn.execute(
            text("SELECT raw_text FROM addresses WHERE id = :id"),
            {"id": addr_id},
        ).one_or_none()
        return row.raw_text if row else None

    def get_address_publications(self, addr_id: int, limit: int) -> list[AddressPublicationItem]:
        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT ON (p.id)
                    p.id, p.title, p.publication_year, p.doi,
                    p.doc_type::text AS doc_type,
                    j.title AS journal_title,
                    {contributor_display_name()} AS author_name,
                    sr.source_id
                FROM source_contribution_addresses sca
                JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                JOIN source_records sr ON sr.id = sc.source_record_id
                JOIN publications p ON p.id = sr.publication_id
                LEFT JOIN serials j ON j.id = p.serial_id
                WHERE sca.address_id = :id AND sr.publication_id IS NOT NULL
                ORDER BY p.id, p.publication_year DESC
                LIMIT :lim
            """),
            {"id": addr_id, "lim": limit},
        ).all()
        return [
            AddressPublicationItem(
                id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doi=r.doi,
                doc_type=r.doc_type,
                journal_title=r.journal_title,
                author_name=r.author_name,
                source_id=r.source_id,
            )
            for r in rows
        ]

    def get_address_structures(self, addr_id: int) -> list[AddressStructureSummary]:
        structures_json: list[JsonValue] | None = self._conn.execute(
            text(address_structures_json(":id")), {"id": addr_id}
        ).scalar_one_or_none()
        return [AddressStructureSummary.model_validate(s) for s in (structures_json or [])]

    def get_structure_link(self, addr_id: int, structure_id: int) -> StructureLinkState | None:
        row = self._conn.execute(
            text("""
                SELECT is_confirmed,
                       (matched_form_id IS NOT NULL) AS is_detected
                FROM address_structures
                WHERE address_id = :aid AND structure_id = :sid
            """),
            {"aid": addr_id, "sid": structure_id},
        ).one_or_none()
        return StructureLinkState.model_validate(row._mapping) if row else None

    def addresses_countries(
        self, *, filters: AddressCountryFilter, page: int, per_page: int
    ) -> AddressesCountriesResponse:
        offset = (page - 1) * per_page
        where, binds = _countries_where(filters)

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM addresses a {where}"), binds
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT a.id, a.raw_text, a.countries, a.publication_count,
                       (SELECT json_agg(json_build_object(
                                   'country_code', f.country_code, 'methods', f.methods
                               ) ORDER BY f.country_code)
                        FROM (SELECT acc.country_code, array_agg(acc.method ORDER BY acc.method) AS methods
                              FROM address_country_candidates acc
                              WHERE acc.address_id = a.id
                              GROUP BY acc.country_code) f) AS found_countries
                FROM addresses a
                {where}
                ORDER BY a.publication_count DESC, a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()

        addresses = [
            AddressForCountryAttribution(
                id=r.id,
                raw_text=r.raw_text,
                countries=sorted(r.countries) if r.countries else None,
                found_countries=[FoundCountry.model_validate(f) for f in r.found_countries or []],
                publication_count=r.publication_count,
            )
            for r in rows
        ]

        # La facette pays couvre la présence d'un pays et le pays retenu : elle écarte ces deux critères.
        facet_filters = replace(filters, country_code=None, has_country=None)
        cf_where, cf_binds = _countries_where(facet_filters)
        cf_rows = self._conn.execute(
            text(f"""
                SELECT c AS code, COUNT(*) AS cnt
                FROM addresses a, unnest(a.countries) AS c
                {cf_where}
                GROUP BY c ORDER BY cnt DESC
            """),
            cf_binds,
        ).all()
        country_facets = [FacetOption(value=r.code, count=r.cnt) for r in cf_rows]
        nc_where, nc_binds = _countries_where(replace(facet_filters, has_country=False))
        without_country = self._conn.execute(
            text(f"SELECT COUNT(*) FROM addresses a {nc_where}"), nc_binds
        ).scalar_one()

        return AddressesCountriesResponse(
            total=total,
            page=page,
            per_page=per_page,
            addresses=addresses,
            country_facets=country_facets,
            without_country=without_country,
        )

    def address_stats(self, structure_id: int) -> AddressStatsResponse:
        total_row = self._conn.execute(text("SELECT COUNT(*) AS total FROM addresses")).one()
        total = total_row.total

        row = self._conn.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE ast.matched_form_id IS NOT NULL) AS detected,
                    COUNT(*) FILTER (WHERE ast.is_confirmed IS NULL) AS pending,
                    COUNT(*) FILTER (WHERE ast.is_confirmed = FALSE) AS rejected,
                    COUNT(*) FILTER (WHERE ast.is_confirmed = TRUE) AS confirmed
                FROM address_structures ast
                WHERE ast.structure_id = :sid
            """),
            {"sid": structure_id},
        ).one()

        return AddressStatsResponse(
            total=total,
            detected=row.detected,
            pending=row.pending,
            rejected=row.rejected,
            confirmed=row.confirmed,
        )
