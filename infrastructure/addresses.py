"""Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`.

Crée les adresses et les liens `source_authorship_addresses` au moment
de l'INSERT des source_authorships. Le cache instance-level évite les
lookups répétés dans un même run.

Dispatche sur le type du premier argument : curseur psycopg (mode
legacy) ou `Connection` SA (mode cible). Le dispatch disparaît quand
tous les normalizers seront migrés en SA.
"""

from typing import Any

from sqlalchemy import Connection
from sqlalchemy import text as sa_text

from domain.normalize import normalize_text


class PgAddressLinker:
    """Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`."""

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_or_create_address(self, conn_or_cur: Any, text: str) -> int | None:
        addr_id = self._cache.get(text)
        if addr_id is not None:
            return addr_id

        norm = normalize_text(text)
        if isinstance(conn_or_cur, Connection):
            row = conn_or_cur.execute(
                sa_text("""
                    INSERT INTO addresses (raw_text, normalized_text)
                    VALUES (:raw, :norm)
                    ON CONFLICT (md5(raw_text)) DO NOTHING
                    RETURNING id
                """),
                {"raw": text, "norm": norm},
            ).one_or_none()
            if row:
                addr_id = row.id
            else:
                row = conn_or_cur.execute(
                    sa_text("SELECT id FROM addresses WHERE md5(raw_text) = md5(:raw)"),
                    {"raw": text},
                ).one_or_none()
                addr_id = row.id if row else None
        else:
            conn_or_cur.execute(
                """
                INSERT INTO addresses (raw_text, normalized_text)
                VALUES (%s, %s)
                ON CONFLICT (md5(raw_text)) DO NOTHING
                RETURNING id
                """,
                (text, norm),
            )
            row = conn_or_cur.fetchone()
            if row:
                addr_id = row[0] if isinstance(row, tuple) else row["id"]
            else:
                conn_or_cur.execute(
                    "SELECT id FROM addresses WHERE md5(raw_text) = md5(%s)", (text,)
                )
                row = conn_or_cur.fetchone()
                if row:
                    addr_id = row[0] if isinstance(row, tuple) else row["id"]
                else:
                    addr_id = None

        if addr_id:
            self._cache[text] = addr_id
        return addr_id

    def link(
        self,
        conn_or_cur: Any,
        authorship_id: int,
        addr_texts: list[str],
        countries: list[str] | None = None,
    ) -> int:
        if not addr_texts:
            return 0

        links = 0
        is_sa = isinstance(conn_or_cur, Connection)
        for raw_text in addr_texts:
            text = raw_text.strip()
            if not text:
                continue

            addr_id = self._get_or_create_address(conn_or_cur, text)
            if not addr_id:
                continue

            # Propager les pays si fournis et pas encore renseignés
            if countries:
                if is_sa:
                    conn_or_cur.execute(
                        sa_text("""
                            UPDATE addresses SET countries = :countries
                            WHERE id = :addr_id AND countries IS NULL
                        """),
                        {"countries": countries, "addr_id": addr_id},
                    )
                else:
                    conn_or_cur.execute(
                        """
                        UPDATE addresses SET countries = %s
                        WHERE id = %s AND countries IS NULL
                        """,
                        (countries, addr_id),
                    )

            if is_sa:
                conn_or_cur.execute(
                    sa_text("""
                        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
                        VALUES (:sa_id, :addr_id)
                        ON CONFLICT (source_authorship_id, address_id) DO NOTHING
                    """),
                    {"sa_id": authorship_id, "addr_id": addr_id},
                )
            else:
                conn_or_cur.execute(
                    """
                    INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
                    VALUES (%s, %s)
                    ON CONFLICT (source_authorship_id, address_id) DO NOTHING
                    """,
                    (authorship_id, addr_id),
                )
            links += 1

        return links
