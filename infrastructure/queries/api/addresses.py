"""Query services sync pour /api/addresses/* et /api/countries.

`PgAddressesQueries` hérite explicitement du Protocol `application.ports.addresses_queries.AddressesQueries` : mypy vérifie la conformité à la définition de classe. Les dataclasses de filtres (`AddressListFilters`, `AddressCountriesFilters`) sont importées du port pour typer les signatures (cf. règle 3 d'`architecture.md`).
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.addresses_queries import (
    AddressCountriesFilters,
    AddressesCountriesResponse,
    AddressesQueries,
    AddressForCountryAttribution,
    AddressListFilters,
    AddressListResponse,
    AddressOut,
    AddressPublicationItem,
    AddressStatsResponse,
    AddressStructureSummary,
    CountryOut,
    CountrySuggestion,
    CountrySuggestionsResponse,
)

# « Reconnue » comme une structure = lien pending (détecté, non revu) ou confirmé.
# Exclut le rejeté (is_confirmed = FALSE) et l'absence de lien. Utilisé par les
# prédicats Structure de `list_addresses`.
_RECOGNIZED_LINK = (
    "((asx.matched_form_id IS NOT NULL AND asx.is_confirmed IS NULL) OR asx.is_confirmed = TRUE)"
)


def _structure_summary(d: dict[str, Any]) -> AddressStructureSummary:
    return AddressStructureSummary(
        id=d["id"],
        name=d["name"],
        acronym=d.get("acronym"),
        is_confirmed=d.get("is_confirmed"),
        is_detected=d["is_detected"],
    )


class PgAddressesQueries(AddressesQueries):
    """Adapter SA sync pour `application.ports.addresses_queries.AddressesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_default_structure_id(self) -> int:
        """Résout la structure de travail par défaut (première racine du périmètre).

        Lit `perimeters.structure_ids[1]` pour le périmètre configuré dans `config.perimeter_persons`. Retourne 0 si la config est absente ou si le périmètre n'a aucune structure (les filtres aval sont alors sans effet).
        """
        row = self._conn.execute(
            text("""
                SELECT p.structure_ids[1] AS root_id
                FROM config c
                JOIN perimeters p ON p.code = c.value #>> '{}'
                WHERE c.key = 'perimeter_persons'
            """)
        ).one_or_none()
        if row and row.root_id:
            return row.root_id
        return 0

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
        binds: dict[str, Any] = {"sid": structure_id}

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

        for i, sp in enumerate(filters.structure_predicates):
            if not sp.structure_ids:
                continue
            bind = f"sids{i}"
            binds[bind] = list(sp.structure_ids)
            exists = (
                "EXISTS (SELECT 1 FROM address_structures asx "
                f"WHERE asx.address_id = a.id AND asx.structure_id = ANY(:{bind}) "
                f"AND {_RECOGNIZED_LINK})"
            )
            # recognized = reconnue comme au moins une des structures (OR) ;
            # not_recognized = reconnue comme aucune (De Morgan → NOT EXISTS).
            parts.append(exists if sp.operator == "recognized" else f"NOT {exists}")

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
                SELECT a.id, a.raw_text, a.pub_count,
                       ast_filter.is_confirmed,
                       (ast_filter.matched_form_id IS NOT NULL) AS is_detected,
                       (SELECT json_agg(json_build_object(
                                   'id', s.id, 'name', s.name, 'acronym', s.acronym,
                                   'is_confirmed', ast2.is_confirmed,
                                   'is_detected', (ast2.matched_form_id IS NOT NULL)
                               ) ORDER BY COALESCE(s.acronym, s.name))
                        FROM address_structures ast2
                        JOIN structures s ON s.id = ast2.structure_id
                        WHERE ast2.address_id = a.id AND s.structure_type != 'site'
                       ) AS structures
                {from_clause}
                ORDER BY a.pub_count DESC, a.id
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
                structures=[_structure_summary(s) for s in (r.structures or [])],
                pub_count=r.pub_count,
            )
            for r in rows
        ]

        return AddressListResponse(
            total=total,
            page=page,
            per_page=per_page,
            pages=(total + per_page - 1) // per_page,
            addresses=addresses,
        )

    def get_address_raw_text(self, addr_id: int) -> str | None:
        row = self._conn.execute(
            text("SELECT raw_text FROM addresses WHERE id = :id"),
            {"id": addr_id},
        ).one_or_none()
        return row.raw_text if row else None

    def get_address_publications(self, addr_id: int, limit: int) -> list[AddressPublicationItem]:
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT ON (p.id)
                    p.id, p.title, p.pub_year, p.doi,
                    p.doc_type::text AS doc_type,
                    j.title AS journal_title,
                    sa.raw_author_name AS author_name,
                    sd.source_id
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN publications p ON p.id = sd.publication_id
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE saa.address_id = :id AND sd.publication_id IS NOT NULL
                ORDER BY p.id, p.pub_year DESC
                LIMIT :lim
            """),
            {"id": addr_id, "lim": limit},
        ).all()
        return [
            AddressPublicationItem(
                id=r.id,
                title=r.title,
                pub_year=r.pub_year,
                doi=r.doi,
                doc_type=r.doc_type,
                journal_title=r.journal_title,
                author_name=r.author_name,
                source_id=r.source_id,
            )
            for r in rows
        ]

    def get_address_structures(self, addr_id: int) -> list[AddressStructureSummary]:
        row = self._conn.execute(
            text("""
                SELECT json_agg(json_build_object(
                           'id', s.id, 'name', s.name, 'acronym', s.acronym,
                           'is_confirmed', ast2.is_confirmed,
                           'is_detected', (ast2.matched_form_id IS NOT NULL)
                       ) ORDER BY COALESCE(s.acronym, s.name)) AS structures
                FROM address_structures ast2
                JOIN structures s ON s.id = ast2.structure_id
                WHERE ast2.address_id = :id AND s.structure_type != 'site'
            """),
            {"id": addr_id},
        ).one_or_none()
        return [_structure_summary(s) for s in (row.structures if row and row.structures else [])]

    def get_structure_link(self, addr_id: int, structure_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            text("""
                SELECT is_confirmed,
                       (matched_form_id IS NOT NULL) AS is_detected
                FROM address_structures
                WHERE address_id = :aid AND structure_id = :sid
            """),
            {"aid": addr_id, "sid": structure_id},
        ).one_or_none()
        return dict(row._mapping) if row else None

    def list_countries(self) -> list[CountryOut]:
        rows = self._conn.execute(
            text("SELECT code, name FROM countries ORDER BY (code = 'xx') DESC, name")
        ).all()
        return [CountryOut(code=r.code, name=r.name) for r in rows]

    def country_exists(self, code: str) -> bool:
        row = self._conn.execute(
            text("SELECT code FROM countries WHERE code = :code"),
            {"code": code},
        ).one_or_none()
        return row is not None

    def address_exists(self, addr_id: int) -> bool:
        row = self._conn.execute(
            text("SELECT id FROM addresses WHERE id = :id"),
            {"id": addr_id},
        ).one_or_none()
        return row is not None

    def addresses_countries(
        self, *, filters: AddressCountriesFilters, page: int, per_page: int
    ) -> AddressesCountriesResponse:
        offset = (page - 1) * per_page
        parts: list[str] = []
        binds: dict[str, Any] = {}

        if filters.search:
            parts.append("unaccent(a.raw_text) ILIKE unaccent(:search)")
            binds["search"] = f"%{filters.search}%"
        if filters.has_country == "yes":
            parts.append("a.countries IS NOT NULL")
        elif filters.has_country == "no":
            parts.append("a.countries IS NULL")
        # Match insensible à la casse : les codes pays sont canoniquement en
        # minuscules (`countries.code`) mais les arrays peuvent contenir des
        # variantes majuscules (codes ISO OpenAlex). Cf. dedup `lower(...)` plus bas.
        if filters.country_code:
            parts.append(
                "EXISTS (SELECT 1 FROM unnest(a.countries) x WHERE lower(x) = lower(:country_code))"
            )
            binds["country_code"] = filters.country_code
        if filters.suggested_country:
            parts.append(
                "EXISTS (SELECT 1 FROM unnest(a.suggested_countries) x "
                "WHERE lower(x) = lower(:suggested_country))"
            )
            binds["suggested_country"] = filters.suggested_country

        where = "WHERE " + " AND ".join(parts) if parts else ""

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM addresses a {where}"),
            binds,
        ).one()
        total = total_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT a.id, a.raw_text, a.countries, a.suggested_countries, a.pub_count
                FROM addresses a
                {where}
                ORDER BY a.pub_count DESC, a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()

        addresses: list[AddressForCountryAttribution] = []
        for r in rows:
            sc = r.suggested_countries
            # Dédup + normalisation casse (un code peut apparaître en 'FR' et 'fr').
            suggestions = (
                [
                    CountrySuggestion(code=code, count=1)
                    for code in sorted({c.strip().lower() for c in sc if c.strip()})
                ]
                if filters.suggest and not r.countries and sc
                else []
            )
            addresses.append(
                AddressForCountryAttribution(
                    id=r.id,
                    raw_text=r.raw_text,
                    countries=(
                        sorted({c.strip().lower() for c in r.countries}) if r.countries else None
                    ),
                    suggested_countries=suggestions,
                    pub_count=r.pub_count,
                )
            )

        suggestion_facets: list[CountrySuggestion] | None = None
        if filters.suggest and not filters.suggested_country:
            extra = "a.suggested_countries IS NOT NULL"
            sug_where = f"{where} AND {extra}" if where else f"WHERE {extra}"
            sug_rows = self._conn.execute(
                text(f"""
                    SELECT lower(c) AS code, COUNT(*) AS cnt
                    FROM addresses a, unnest(a.suggested_countries) AS c
                    {sug_where}
                    GROUP BY lower(c) ORDER BY cnt DESC LIMIT 20
                """),
                binds,
            ).all()
            suggestion_facets = [CountrySuggestion(code=r.code, count=r.cnt) for r in sug_rows]

        # Facette pays (exclut country_code, garde le reste + a.countries IS NOT NULL).
        cf_parts: list[str] = []
        cf_binds: dict[str, Any] = {}
        if filters.search:
            cf_parts.append("unaccent(a.raw_text) ILIKE unaccent(:cf_search)")
            cf_binds["cf_search"] = f"%{filters.search}%"
        if filters.has_country == "yes":
            cf_parts.append("a.countries IS NOT NULL")
        elif filters.has_country == "no":
            cf_parts.append("a.countries IS NULL")
        if filters.suggested_country:
            cf_parts.append(
                "EXISTS (SELECT 1 FROM unnest(a.suggested_countries) x "
                "WHERE lower(x) = lower(:cf_suggested))"
            )
            cf_binds["cf_suggested"] = filters.suggested_country
        cf_parts.append("a.countries IS NOT NULL")
        cf_where = "WHERE " + " AND ".join(cf_parts)
        cf_rows = self._conn.execute(
            text(f"""
                SELECT lower(c) AS code, COUNT(*) AS cnt
                FROM addresses a, unnest(a.countries) AS c
                {cf_where}
                GROUP BY lower(c) ORDER BY cnt DESC
            """),
            cf_binds,
        ).all()
        country_facets = [CountrySuggestion(code=r.code, count=r.cnt) for r in cf_rows]

        return AddressesCountriesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pages=(total + per_page - 1) // per_page or 1,
            addresses=addresses,
            suggestion_facets=suggestion_facets,
            country_facets=country_facets,
        )

    def suggest_countries(self, search: str) -> CountrySuggestionsResponse:
        binds: dict[str, Any] = {}
        where_clause = ""
        if search.strip():
            where_clause = "WHERE unaccent(a.raw_text) ILIKE unaccent(:search)"
            binds["search"] = f"%{search.strip()}%"

        suggest_where = (
            where_clause.replace("WHERE", "WHERE a.countries IS NOT NULL AND")
            if where_clause
            else "WHERE a.countries IS NOT NULL"
        )
        sug_rows = self._conn.execute(
            text(f"""
                SELECT lower(c) AS c, COUNT(*) AS cnt
                FROM addresses a, unnest(a.countries) AS c
                {suggest_where}
                GROUP BY lower(c) ORDER BY cnt DESC
            """),
            binds,
        ).all()
        suggestions = [CountrySuggestion(code=r.c, count=r.cnt) for r in sug_rows]

        no_country_where = (
            where_clause.replace("WHERE", "WHERE countries IS NULL AND")
            if where_clause
            else "WHERE countries IS NULL"
        )
        nc_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM addresses a {no_country_where}"),
            binds,
        ).one()

        return CountrySuggestionsResponse(suggestions=suggestions, without_country=nc_row.total)

    def admin_address_stats(self, structure_id: int) -> AddressStatsResponse:
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
