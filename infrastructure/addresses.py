"""Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`.

Crée les adresses et les liens `source_authorship_addresses` au moment
de l'INSERT des source_authorships. Le cache instance-level évite les
lookups répétés dans un même run.
"""

from typing import Any

from domain.normalize import normalize_text


class PgAddressLinker:
    """Adapter PostgreSQL pour `application.ports.address_linker.AddressLinker`."""

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_or_create_address(self, cur: Any, text: str) -> int | None:
        addr_id = self._cache.get(text)
        if addr_id is not None:
            return addr_id

        norm = normalize_text(text)
        cur.execute(
            """
            INSERT INTO addresses (raw_text, normalized_text)
            VALUES (%s, %s)
            ON CONFLICT (md5(raw_text)) DO NOTHING
            RETURNING id
            """,
            (text, norm),
        )
        row = cur.fetchone()
        if row:
            addr_id = row[0] if isinstance(row, tuple) else row["id"]
        else:
            cur.execute("SELECT id FROM addresses WHERE md5(raw_text) = md5(%s)", (text,))
            row = cur.fetchone()
            if row:
                addr_id = row[0] if isinstance(row, tuple) else row["id"]
            else:
                addr_id = None

        if addr_id:
            self._cache[text] = addr_id
        return addr_id

    def link(
        self,
        cur: Any,
        authorship_id: int,
        addr_texts: list[str],
        countries: list[str] | None = None,
    ) -> int:
        if not addr_texts:
            return 0

        links = 0
        for raw_text in addr_texts:
            text = raw_text.strip()
            if not text:
                continue

            addr_id = self._get_or_create_address(cur, text)
            if not addr_id:
                continue

            # Propager les pays si fournis et pas encore renseignés
            if countries:
                cur.execute(
                    """
                    UPDATE addresses SET countries = %s
                    WHERE id = %s AND countries IS NULL
                    """,
                    (countries, addr_id),
                )

            cur.execute(
                """
                INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
                VALUES (%s, %s)
                ON CONFLICT (source_authorship_id, address_id) DO NOTHING
                """,
                (authorship_id, addr_id),
            )
            links += 1

        return links
