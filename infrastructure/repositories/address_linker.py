"""Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`.

Crée les adresses et les liens `source_authorship_addresses` au moment de l'INSERT des source_authorships. Le cache instance-level évite les lookups répétés dans un même run.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.address_pub_count import AddressPubCountQueries
from domain.normalize import normalize_text, sanitize_raw_text


def recompute_pub_count(conn: Connection) -> int:
    """Recalcule `addresses.pub_count` = nb de publications canoniques distinctes
    liées à l'adresse via `source_authorship_addresses`.

    Recompute global idempotent (guard `IS DISTINCT FROM`) couvrant **toutes**
    les adresses : celles qui ont perdu tous leurs liens repassent à 0. Lancé en
    fin de phase `publications`, une fois les publications créées et fusionnées —
    il n'y a rien à compter au stade `normalize`. Un run `--only publications`
    suffit à tenir le décompte à jour.

    Ne committe pas (le caller orchestre). Retourne le nombre de rows modifiées.
    """
    return conn.execute(
        text("""
            UPDATE addresses a
            SET pub_count = COALESCE(sub.cnt, 0)
            FROM (
                SELECT a2.id AS address_id, agg.cnt
                FROM addresses a2
                LEFT JOIN (
                    SELECT saa.address_id, COUNT(DISTINCT sd.publication_id) AS cnt
                    FROM source_authorship_addresses saa
                    JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sd.publication_id IS NOT NULL
                    GROUP BY saa.address_id
                ) agg ON agg.address_id = a2.id
            ) sub
            WHERE a.id = sub.address_id
              AND a.pub_count IS DISTINCT FROM COALESCE(sub.cnt, 0)
        """)
    ).rowcount


class PgAddressPubCountQueries(AddressPubCountQueries):
    """Adapter PostgreSQL pour le port `AddressPubCountQueries`."""

    def recompute_pub_count(self, conn: Connection) -> int:
        return recompute_pub_count(conn)


class PgAddressLinker:
    """Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`."""

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_or_create_address(self, conn: Connection, raw_text: str) -> int | None:
        addr_id = self._cache.get(raw_text)
        if addr_id is not None:
            return addr_id

        norm = normalize_text(raw_text)
        row = conn.execute(
            text("""
                INSERT INTO addresses (raw_text, normalized_text)
                VALUES (:raw, :norm)
                ON CONFLICT (md5(raw_text)) DO NOTHING
                RETURNING id
            """),
            {"raw": raw_text, "norm": norm},
        ).one_or_none()
        if row:
            addr_id = row.id
        else:
            row = conn.execute(
                text("SELECT id FROM addresses WHERE md5(raw_text) = md5(:raw)"),
                {"raw": raw_text},
            ).one_or_none()
            addr_id = row.id if row else None

        if addr_id:
            self._cache[raw_text] = addr_id
        return addr_id

    def link(
        self,
        conn: Connection,
        authorship_id: int,
        addr_texts: list[str],
        countries: list[str] | None = None,
        suggested_countries: list[str] | None = None,
    ) -> int:
        if not addr_texts:
            return 0

        links = 0
        for raw_text in addr_texts:
            text_clean = sanitize_raw_text(raw_text)
            if not text_clean:
                continue

            addr_id = self._get_or_create_address(conn, text_clean)
            if not addr_id:
                continue

            # Propager les pays si fournis et pas encore renseignés
            if countries:
                conn.execute(
                    text("""
                        UPDATE addresses SET countries = :countries
                        WHERE id = :addr_id AND countries IS NULL
                    """),
                    {"countries": countries, "addr_id": addr_id},
                )

            # Suggestion de pays (OpenAlex country_code) : seulement si l'adresse
            # n'a ni pays d'autorité ni suggestion. Jamais écrasée.
            if suggested_countries:
                conn.execute(
                    text("""
                        UPDATE addresses SET suggested_countries = :sc
                        WHERE id = :addr_id
                          AND countries IS NULL
                          AND suggested_countries IS NULL
                    """),
                    {"sc": suggested_countries, "addr_id": addr_id},
                )

            conn.execute(
                text("""
                    INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
                    VALUES (:sa_id, :addr_id)
                    ON CONFLICT (source_authorship_id, address_id) DO NOTHING
                """),
                {"sa_id": authorship_id, "addr_id": addr_id},
            )
            links += 1

        return links
