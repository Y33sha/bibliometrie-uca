"""SQL de la phase `countries` : résoudre les pays d'une adresse, puis les recopier dans les caches dénormalisés.

**Candidats et résolution** — chaque moyen de détection ajoute ses pays candidats à `address_country_candidates` (`insert_candidates`, `insert_ror_candidates`) et marque l'adresse `candidates_dirty`. La détection par le texte confronte les formes de `place_name_forms` (`load_country_forms`, `load_place_forms`) aux adresses marquées (`fetch_dirty_addresses_normalized`). `resolve_address_countries` compose ensuite `addresses.countries` par la préséance du domaine. Suggestion : les adresses déjà résolues forment un pool (`load_country_pool`) rapproché des cibles restantes (`fetch_suggest_targets_chunk`) pour alimenter `addresses.suggested_countries`. `count_address_country_status` et `count_suggest_eligible` en donnent le bilan.

**Recopie** — recalcule trois caches en cascade :

1. `source_authorships.countries` ← pays retenus des adresses de la signature, pays de ses organisations ROR sans adresse, pays de ses structures HAL.
2. `source_publications.countries` ← union des `source_authorships.countries` du document.
3. `publications.countries` ← union des `source_publications.countries` de même `publication_id`.

Deux portées partagent l'agrégation (`_SA_COUNTRIES_FROM_SCOPE` / `_SP_COUNTRIES_FROM_SCOPE` / `_PUB_COUNTRIES_FROM_SCOPE`) : bornée aux `countries_dirty` (`refresh_signature_countries` / `refresh_address_source_countries` / `refresh_publication_countries`, cf. `_DIRTY_SA`), ou bornée à des adresses (`refresh_source_publications_countries_for_addresses` / `refresh_publications_countries_for_addresses`). La seconde sert l'API après une modification manuelle (port `CountryRecompute`).
"""

import json
from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind
from domain.country_detection import CountryDetectionMethod, retained_countries


class SuggestEligibleCounts(NamedTuple):
    """Compteurs des adresses sans pays qui bornent la passe de suggestion."""

    eligible: int  # aucune suggestion tentée
    empty_attempted: int  # tentées sans match (`= []`) — retraitées en mode retry_empty


class AddressCountryStatus(NamedTuple):
    """Bilan de l'état pays des adresses (restreint à `pub_count > 0`)."""

    total: int
    with_country: int
    with_suggestion: int
    none: int


# CTE des signatures à recalculer : marquées `countries_dirty`, ou liées à une adresse marquée `countries_dirty`.
_DIRTY_SA = """
    WITH dirty_sa AS (
        SELECT id FROM source_authorships WHERE countries_dirty
        UNION
        SELECT saa.source_authorship_id
        FROM source_authorship_addresses saa
        JOIN addresses a ON a.id = saa.address_id
        WHERE a.countries_dirty
    )
"""

# Recalcul de `source_authorships.countries` sur la CTE amont `scoped_sa(id)` ; marque `countries_dirty` les signatures modifiées.
_SA_COUNTRIES_FROM_SCOPE = """,
    contributions AS (
        SELECT saa.source_authorship_id AS sa_id, c::text AS code
        FROM scoped_sa s
        JOIN source_authorship_addresses saa ON saa.source_authorship_id = s.id
        JOIN addresses a ON a.id = saa.address_id
        CROSS JOIN LATERAL unnest(a.countries) AS c
        UNION
        SELECT sar.source_authorship_id, ro.country_code::text
        FROM scoped_sa s
        JOIN source_authorship_rors sar ON sar.source_authorship_id = s.id
        JOIN ror_organizations ro ON ro.ror_id = sar.ror_id
        WHERE sar.address_id IS NULL
        UNION
        SELECT h.source_authorship_id, hs.country_code::text
        FROM scoped_sa s
        JOIN source_authorship_hal_structures h ON h.source_authorship_id = s.id
        LEFT JOIN hal_structure_aliases al ON al.alias_id = h.hal_structure_id
        JOIN hal_structures hs ON hs.hal_structure_id = coalesce(al.hal_structure_id, h.hal_structure_id)
        WHERE hs.country_code IS NOT NULL
    ),
    agg AS (
        SELECT sa_id, array_agg(code ORDER BY code) AS new_countries
        FROM contributions
        GROUP BY sa_id
    )
    UPDATE source_authorships sa
    SET countries = agg.new_countries, countries_dirty = true
    FROM scoped_sa s
    LEFT JOIN agg ON agg.sa_id = s.id
    WHERE sa.id = s.id
      AND sa.countries IS DISTINCT FROM agg.new_countries
"""

# Recalcul de `source_publications.countries` sur la CTE amont `scoped_sp(sp_id)` : union des pays des signatures.
_SP_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sa.source_publication_id AS sp_id,
               array_agg(DISTINCT c ORDER BY c) AS new_countries
        FROM source_authorships sa
        JOIN scoped_sp ss ON ss.sp_id = sa.source_publication_id
        CROSS JOIN LATERAL unnest(sa.countries) AS c
        GROUP BY sa.source_publication_id
    )
    UPDATE source_publications sp
    SET countries = agg.new_countries
    FROM scoped_sp ss
    LEFT JOIN agg ON agg.sp_id = ss.sp_id
    WHERE sp.id = ss.sp_id
      AND sp.countries IS DISTINCT FROM agg.new_countries
"""

# Tail partagé du recalcul `publications.countries` : attend une CTE amont
# `scoped_pub(pub_id)`. Union des `source_publications.countries` de la
# publication ; n'écrit que les lignes qui changent (LEFT JOIN → NULL si aucune).
_PUB_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sp.publication_id AS pub_id,
               array_agg(DISTINCT c::text ORDER BY c::text) AS new_countries
        FROM source_publications sp
        JOIN scoped_pub spp ON spp.pub_id = sp.publication_id
        CROSS JOIN LATERAL unnest(sp.countries) AS c
        WHERE sp.countries IS NOT NULL
        GROUP BY sp.publication_id
    )
    UPDATE publications p
    SET countries = agg.new_countries
    FROM scoped_pub spp
    LEFT JOIN agg ON agg.pub_id = spp.pub_id
    WHERE p.id = spp.pub_id
      AND p.countries IS DISTINCT FROM agg.new_countries
"""


# Fin partagée des insertions de candidats : attend une CTE `added(address_id)` des candidats ajoutés, marque leurs adresses à traiter et compte les candidats.
_MARK_DIRTY = """,
    marked AS (
        UPDATE addresses SET candidates_dirty = true
        WHERE id IN (SELECT address_id FROM added) AND NOT candidates_dirty
    )
    SELECT count(*) FROM added
"""

# Adresses résolues par lot : chaque lot charge ses candidats en mémoire.
_RESOLVE_BATCH = 50_000


class CountryQueries:
    """Requêtes de la phase `countries`."""

    def count_address_country_status(self, conn: Connection) -> AddressCountryStatus:
        """Bilan de la résolution des pays sur les adresses utiles (`pub_count > 0`)."""
        row = conn.execute(
            text("""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE countries IS NOT NULL) AS with_country,
                    count(*) FILTER (
                        WHERE countries IS NULL AND cardinality(suggested_countries) > 0
                    ) AS with_suggestion,
                    count(*) FILTER (
                        WHERE countries IS NULL
                          AND (suggested_countries IS NULL OR cardinality(suggested_countries) = 0)
                    ) AS none
                FROM addresses
                WHERE pub_count > 0
            """)
        ).one()
        return AddressCountryStatus(row.total, row.with_country, row.with_suggestion, row.none)

    def refresh_signature_countries(
        self, conn: Connection, *, id_range: tuple[int, int] | None = None
    ) -> int:
        """Recalcule `source_authorships.countries` des signatures de `_DIRTY_SA`. Retourne le nombre de signatures modifiées.

        `id_range` (bornes incluses) recalcule toutes les signatures de l'intervalle qui ont une adresse, un ROR sans adresse ou une structure HAL.
        """
        if id_range is None:
            scope = _DIRTY_SA + ", scoped_sa AS (SELECT id FROM dirty_sa)"
            params = {}
        else:
            scope = """
                WITH scoped_sa AS (
                    SELECT source_authorship_id AS id FROM source_authorship_addresses
                    WHERE source_authorship_id BETWEEN :lo AND :hi
                    UNION
                    SELECT source_authorship_id FROM source_authorship_rors
                    WHERE source_authorship_id BETWEEN :lo AND :hi AND address_id IS NULL
                    UNION
                    SELECT source_authorship_id FROM source_authorship_hal_structures
                    WHERE source_authorship_id BETWEEN :lo AND :hi
                )"""
            params = {"lo": id_range[0], "hi": id_range[1]}
        return conn.execute(text(scope + _SA_COUNTRIES_FROM_SCOPE), params).rowcount

    def refresh_address_source_countries(self, conn: Connection) -> int:
        """Recalcule `source_publications.countries` — union des `source_authorships.countries` du document — sur les documents qu'un flag `countries_dirty` signale. Retourne le nombre de lignes modifiées."""
        return conn.execute(
            text(
                _DIRTY_SA
                + """,
                scoped_sp AS (
                    SELECT DISTINCT sa.source_publication_id AS sp_id
                    FROM source_authorships sa
                    JOIN dirty_sa d ON d.id = sa.id
                    WHERE sa.source_publication_id IS NOT NULL
                )
                """
                + _SP_COUNTRIES_FROM_SCOPE
            )
        ).rowcount

    def refresh_publication_countries(self, conn: Connection) -> int:
        """Recalcule `publications.countries` — union des `source_publications.countries` de la publication — sur les publications qu'un flag `countries_dirty` signale. Retourne le nombre de lignes modifiées."""
        return conn.execute(
            text(
                _DIRTY_SA
                + """,
                scoped_pub AS (
                    SELECT DISTINCT sp.publication_id AS pub_id
                    FROM source_publications sp
                    JOIN source_authorships sa ON sa.source_publication_id = sp.id
                    JOIN dirty_sa d ON d.id = sa.id
                    WHERE sp.publication_id IS NOT NULL
                )
                """
                + _PUB_COUNTRIES_FROM_SCOPE
            )
        ).rowcount

    def clear_countries_dirty(self, conn: Connection) -> None:
        """Purge les flags `countries_dirty` (`source_authorships` et `addresses`) en fin de cascade."""
        conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE countries_dirty")
        )
        conn.execute(text("UPDATE addresses SET countries_dirty = false WHERE countries_dirty"))

    def load_country_forms(self, conn: Connection) -> dict[str, str]:
        """Formes normalisées des noms de pays, chacune avec le code ISO du pays qu'elle désigne : `{forme: code ISO}`."""
        rows = conn.execute(
            text(
                f"SELECT form_normalized, iso_code FROM place_name_forms "
                f"WHERE kind = '{PlaceNameKind.COUNTRY.value}'"
            )
        ).all()
        return {r.form_normalized: r.iso_code for r in rows}

    def load_place_forms(self, conn: Connection, kind: PlaceNameKind) -> dict[str, str]:
        """Formes normalisées des noms de lieux de nature `kind` (institution ou ville), chacune avec le code ISO du pays où le lieu se situe : `{forme: code ISO}`."""
        rows = conn.execute(
            text("SELECT form_normalized, iso_code FROM place_name_forms WHERE kind = :kind"),
            {"kind": kind.value},
        ).all()
        return {r.form_normalized: r.iso_code for r in rows}

    def fetch_dirty_addresses_normalized(self, conn: Connection) -> list[tuple[int, str]]:
        """`(id, normalized_text)` des adresses à traiter (`candidates_dirty`), pour la détection par le texte."""
        rows = conn.execute(
            text("SELECT id, normalized_text FROM addresses WHERE candidates_dirty")
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def insert_candidates(
        self,
        conn: Connection,
        method: CountryDetectionMethod,
        rows: list[tuple[int, list[str]]],
    ) -> int:
        """Ajoute les candidats `(adresse, pays)` de `rows` pour le moyen `method`, et marque `candidates_dirty` les adresses qui en reçoivent un. Un candidat déjà présent, ou un code absent du référentiel des pays, est ignoré. Retourne le nombre de candidats ajoutés."""
        if not rows:
            return 0
        payload = json.dumps([{"id": addr_id, "c": codes} for addr_id, codes in rows])
        return conn.execute(
            text(
                """
                WITH proposed AS (
                    SELECT DISTINCT (e->>'id')::int AS address_id, code.value AS country_code
                    FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
                    CROSS JOIN LATERAL jsonb_array_elements_text(e->'c') code
                    JOIN countries c ON c.code = code.value
                ), added AS (
                    INSERT INTO address_country_candidates (address_id, country_code, method)
                    SELECT address_id, country_code, CAST(:method AS country_detection_method)
                    FROM proposed
                    ON CONFLICT DO NOTHING
                    RETURNING address_id
                )"""
                + _MARK_DIRTY
            ),
            {"payload": payload, "method": method.value},
        ).scalar_one()

    def insert_ror_candidates(self, conn: Connection) -> int:
        """Ajoute le pays de chaque organisation ROR rattachée à l'affiliation d'une adresse (candidat `ror`), et marque `candidates_dirty` les adresses qui en reçoivent un. Retourne le nombre de candidats ajoutés."""
        return conn.execute(
            text(
                """
                WITH added AS (
                    INSERT INTO address_country_candidates (address_id, country_code, method)
                    SELECT DISTINCT sar.address_id, ro.country_code, 'ror'::country_detection_method
                    FROM source_authorship_rors sar
                    JOIN ror_organizations ro ON ro.ror_id = sar.ror_id
                    JOIN countries c ON c.code = ro.country_code
                    WHERE sar.address_id IS NOT NULL
                    ON CONFLICT DO NOTHING
                    RETURNING address_id
                )"""
                + _MARK_DIRTY
            )
        ).scalar_one()

    def resolve_address_countries(
        self, conn: Connection, address_ids: list[int] | None = None
    ) -> int:
        """Compose `addresses.countries` à partir des candidats par la préséance du domaine (`retained_countries`), pour `address_ids`, ou pour les adresses `candidates_dirty` quand `address_ids` vaut `None`. Une adresse sans candidat perd son pays. Pose `countries_dirty` là où le pays change, efface `candidates_dirty`. Retourne le nombre d'adresses dont le pays change."""
        if address_ids is None:
            address_ids = list(
                conn.execute(text("SELECT id FROM addresses WHERE candidates_dirty")).scalars()
            )
        changed = 0
        for start in range(0, len(address_ids), _RESOLVE_BATCH):
            ids = address_ids[start : start + _RESOLVE_BATCH]
            candidates: defaultdict[int, defaultdict[CountryDetectionMethod, list[str]]] = (
                defaultdict(lambda: defaultdict(list))
            )
            for r in conn.execute(
                text(
                    "SELECT address_id, country_code, method::text AS method"
                    " FROM address_country_candidates WHERE address_id = ANY(:ids)"
                ),
                {"ids": ids},
            ):
                candidates[r.address_id][CountryDetectionMethod(r.method)].append(r.country_code)
            payload = json.dumps(
                [
                    {"id": addr_id, "c": sorted(retained_countries(candidates.get(addr_id, {})))}
                    for addr_id in ids
                ]
            )
            changed += conn.execute(
                text("""
                    UPDATE addresses a
                    SET countries = d.cty, countries_dirty = true
                    FROM (
                        SELECT (e->>'id')::int AS id,
                               nullif(ARRAY(SELECT jsonb_array_elements_text(e->'c'))::char(2)[],
                                      '{}'::char(2)[]) AS cty
                        FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
                    ) d
                    WHERE a.id = d.id AND a.countries IS DISTINCT FROM d.cty
                """),
                {"payload": payload},
            ).rowcount
            conn.execute(
                text(
                    "UPDATE addresses SET candidates_dirty = false"
                    " WHERE id = ANY(:ids) AND candidates_dirty"
                ),
                {"ids": ids},
            )
        return changed

    def count_suggest_eligible(self, conn: Connection) -> SuggestEligibleCounts:
        """Compte les adresses sans pays selon ce que la passe de suggestion en fait : à traiter, déjà suggérées, déjà tentées sans match. Les trois ensembles partitionnent les adresses sans pays."""
        row = conn.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE suggested_countries IS NULL) AS eligible,
                    COUNT(*) FILTER (
                        WHERE suggested_countries IS NOT NULL AND cardinality(suggested_countries) = 0
                    ) AS empty_attempted
                FROM addresses
                WHERE countries IS NULL
            """)
        ).one()
        return SuggestEligibleCounts(row.eligible, row.empty_attempted)

    def fetch_suggest_targets_chunk(
        self, conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
    ) -> list[tuple[int, str]]:
        """Tranche `(id, normalized_text)` des adresses à suggérer, paginée par keyset sur `after_id`. `retry_empty` y joint les adresses tentées sans match, au cas où le pool aurait grossi entre deux runs. Liste vide = parcours terminé."""
        # `retry_empty` (mode full) réessaie aussi les échecs (`= []`), sans toucher aux suggestions positives (rares à changer, coûteuses à recalculer).
        suggested_filter = (
            "AND (suggested_countries IS NULL OR cardinality(suggested_countries) = 0)"
            if retry_empty
            else "AND suggested_countries IS NULL"
        )
        rows = conn.execute(
            text(f"""
                SELECT id, normalized_text
                FROM addresses
                WHERE countries IS NULL
                  {suggested_filter}
                  AND id > :after
                ORDER BY id
                LIMIT :limit
            """),
            {"after": after_id, "limit": limit},
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def load_country_pool(self, conn: Connection) -> list[tuple[str, list[str]]]:
        """Pool de référence de la suggestion : `(normalized_text, countries)` des adresses ayant un pays. Tenu en mémoire, rescanné à chaque batch de cibles."""
        rows = conn.execute(
            text("SELECT normalized_text, countries FROM addresses WHERE countries IS NOT NULL")
        ).all()
        return [(r.normalized_text, r.countries) for r in rows]

    def write_suggested_countries(
        self, conn: Connection, rows: list[tuple[int, list[str]]]
    ) -> None:
        """Écrit en bloc les `(address_id, codes ISO)` de `rows` dans `addresses.suggested_countries` (`[]` = tentée sans match). Idempotent."""
        if not rows:
            return
        payload = json.dumps([{"id": addr_id, "c": countries} for addr_id, countries in rows])
        conn.execute(
            text("""
                UPDATE addresses a
                SET suggested_countries = d.cty
                FROM (
                    SELECT (e->>'id')::int AS id,
                           ARRAY(SELECT jsonb_array_elements_text(e->'c'))::char(2)[] AS cty
                    FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
                ) d
                WHERE a.id = d.id
                  AND a.suggested_countries IS DISTINCT FROM d.cty
            """),
            {"payload": payload},
        )

    def refresh_source_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `source_authorships.countries` des signatures liées à l'une des `address_ids`, puis `source_publications.countries` de leurs documents. Idempotent. Retourne le nombre de documents mis à jour."""
        if not address_ids:
            return 0
        conn.execute(
            text(
                """
                WITH scoped_sa AS (
                    SELECT DISTINCT source_authorship_id AS id
                    FROM source_authorship_addresses
                    WHERE address_id = ANY(:ids)
                )"""
                + _SA_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        )
        return conn.execute(
            text(
                """
                WITH scoped_sp AS (
                    SELECT DISTINCT sa.source_publication_id AS sp_id
                    FROM source_authorship_addresses saa
                    JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                    WHERE saa.address_id = ANY(:ids)
                      AND sa.source_publication_id IS NOT NULL
                )
                """
                + _SP_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        ).rowcount

    def refresh_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `publications.countries` (union des `source_publications.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        if not address_ids:
            return 0
        return conn.execute(
            text(
                """
                WITH scoped_pub AS (
                    SELECT DISTINCT sd.publication_id AS pub_id
                    FROM source_authorship_addresses saa
                    JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE saa.address_id = ANY(:ids) AND sd.publication_id IS NOT NULL
                )
                """
                + _PUB_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        ).rowcount
