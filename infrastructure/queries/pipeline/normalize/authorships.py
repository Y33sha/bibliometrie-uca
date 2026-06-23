"""Query service : SQL batch partagé pour l'écriture des `source_authorships`.

Implémente `application.ports.pipeline.normalize.authorships.AuthorshipsBatchQueries`.
Les colonnes de `source_authorships` sont identiques pour toutes les sources,
seul `source` paramètre l'INSERT. Chaque opération de batch est une **seule**
requête : le lot est transmis en JSONB (ou en tableaux parallèles pour le
pivot) et étendu côté serveur via `jsonb_to_recordset` / `unnest`. Un
`executemany` partirait au contraire en N allers-retours séquentiels côté
psycopg.

Consommé par le writer partagé `write_source_authorships` ; le `clear` en
amont (DELETE, qui cascade sur le pivot) garantit qu'aucune authorship ni lien
ne préexiste — d'où l'absence d'`ON CONFLICT` sur ces deux INSERT (seul
`addresses`, table partagée non vidée, le conserve).
"""

import hashlib

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.authorships import (
    AddressBatchItem,
    AddressCountryItem,
    AuthorshipAddressItem,
    AuthorshipsBatchQueries,
    SourceAuthorshipBatchItem,
)
from infrastructure.queries.pipeline.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_source_authorships_batch(
    conn: Connection, values: list[SourceAuthorshipBatchItem]
) -> None:
    """Batch UPSERT de `source_authorships` (toutes sources, `source` par ligne).

    Une **seule** requête : le batch est transmis en JSONB et étendu côté
    serveur via `jsonb_to_recordset` (vs un `executemany` qui partirait en N
    allers-retours séquentiels côté psycopg). `source`/`source_publication_id`
    sont invariants au sein d'un document (le writer est appelé par document),
    donc hoistés hors du recordset. Le nom normalisé est fourni pré-calculé
    (`author_name_normalized`, via `normalize_name_form` côté Python).
    """
    if not values:
        return
    payload = [
        {
            "author_position": v["author_position"],
            "author_name_normalized": v["author_name_normalized"],
            "is_corresponding": v["is_corresponding"],
            "roles": v["roles"],
            "raw_author_name": v["raw_author_name"],
            "person_identifiers": v["person_identifiers"],
        }
        for v in values
    ]
    # Pas d'ON CONFLICT : le writer DELETE avant d'insérer (clear) et déduplique
    # par position, donc la clé (source_publication_id, author_position) ne peut
    # pas entrer en collision. Un INSERT nu est plus rapide (pas de sonde
    # d'unicité spéculative).
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position,
             author_name_normalized, is_corresponding, roles,
             raw_author_name, person_identifiers)
        SELECT :source, :spid, t.author_position,
               t.author_name_normalized, t.is_corresponding, t.roles,
               t.raw_author_name, t.person_identifiers
        FROM jsonb_to_recordset(:payload) AS t(
            author_position smallint, author_name_normalized text,
            is_corresponding boolean, roles text[],
            raw_author_name text, person_identifiers jsonb)
    """).bindparams(bindparam("payload", type_=JSONB))
    conn.execute(
        stmt,
        {"source": values[0]["source"], "spid": values[0]["spid"], "payload": payload},
    )


def fetch_source_authorship_ids_by_position(
    conn: Connection, *, source: str, source_publication_id: int, positions: list[int]
) -> dict[int, int]:
    """Retourne `{author_position: source_authorship_id}` pour un document."""
    if not positions:
        return {}
    rows = conn.execute(
        text("""
            SELECT author_position, id FROM source_authorships
            WHERE source = :source
              AND source_publication_id = :spid
              AND author_position = ANY(:positions)
        """),
        {"source": source, "spid": source_publication_id, "positions": positions},
    ).all()
    return {r.author_position: r.id for r in rows}


def upsert_addresses_batch(conn: Connection, values: list[AddressBatchItem]) -> None:
    """INSERT INTO addresses ON CONFLICT DO NOTHING pour un batch `[{raw, norm}, ...]`.

    Une seule requête (batch JSONB étendu via `jsonb_to_recordset`).
    """
    if not values:
        return
    stmt = text("""
        INSERT INTO addresses (raw_text, normalized_text)
        SELECT t.raw, t.norm
        FROM jsonb_to_recordset(:payload) AS t(raw text, norm text)
        ON CONFLICT (md5(raw_text)) DO NOTHING
    """).bindparams(bindparam("payload", type_=JSONB))
    conn.execute(stmt, {"payload": list(values)})


def fetch_address_ids_by_raw_text(conn: Connection, raw_texts: list[str]) -> dict[str, int]:
    """Retourne `{raw_text: id}` pour un lot d'adresses.

    Filtre sur `md5(raw_text)` (et non `raw_text`) pour exploiter l'index unique
    fonctionnel `addresses_raw_text_key (md5(raw_text))` — celui-là même qui sert
    le `ON CONFLICT` de `upsert_addresses_batch`. Sans ça, `WHERE raw_text = ANY(...)`
    déclenche un seq scan de toute la table `addresses` à chaque document (coût fixe
    ~0,5 s par publication, indépendant du nombre d'auteurs). `md5()` PostgreSQL et
    `hashlib.md5` sur l'UTF-8 coïncident.
    """
    if not raw_texts:
        return {}
    md5s = [hashlib.md5(t.encode()).hexdigest() for t in raw_texts]
    rows = conn.execute(
        text("SELECT raw_text, id FROM addresses WHERE md5(raw_text) = ANY(:md5s)"),
        {"md5s": md5s},
    ).all()
    return {r.raw_text: r.id for r in rows}


def apply_address_countries_batch(conn: Connection, values: list[AddressCountryItem]) -> None:
    """Propage les pays d'autorité sur `addresses.countries` (jamais d'écrasement).

    Renseigne `countries` uniquement sur les adresses encore sans pays.
    """
    if not values:
        return
    stmt = text("""
        UPDATE addresses a SET countries = t.countries::character(2)[]
        FROM jsonb_to_recordset(:payload) AS t(addr_id integer, countries text[])
        WHERE a.id = t.addr_id AND a.countries IS NULL
    """).bindparams(bindparam("payload", type_=JSONB))
    conn.execute(stmt, {"payload": list(values)})


def apply_address_suggested_countries_batch(
    conn: Connection, values: list[AddressCountryItem]
) -> None:
    """Propage une suggestion de pays sur `addresses.suggested_countries`.

    Renseigne `suggested_countries` uniquement sur les adresses sans pays
    d'autorité ni suggestion existante (jamais d'écrasement).
    """
    if not values:
        return
    conn.execute(
        text("""
            UPDATE addresses SET suggested_countries = :countries
            WHERE id = :addr_id
              AND countries IS NULL
              AND suggested_countries IS NULL
        """),
        values,
    )


def insert_source_authorship_addresses_batch(
    conn: Connection, values: list[AuthorshipAddressItem]
) -> None:
    """Batch INSERT de liens `source_authorship_addresses`. Dicts `{sa_id, addr_id}`.

    Une seule requête : deux colonnes entières transmises en tableaux parallèles
    et étendues via `unnest`. Pas d'ON CONFLICT : les authorships viennent
    d'être (re)créées (le clear a cascadé sur le pivot), leurs `sa_id` sont neufs
    et le writer déduplique les couples (sa_id, addr_id) — aucune collision.
    """
    if not values:
        return
    stmt = text("""
        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
        SELECT sa_id, addr_id
        FROM unnest(:sa_ids ::integer[], :addr_ids ::integer[]) AS t(sa_id, addr_id)
    """)
    conn.execute(
        stmt,
        {
            "sa_ids": [v["sa_id"] for v in values],
            "addr_ids": [v["addr_id"] for v in values],
        },
    )


class PgAuthorshipsBatchQueries(AuthorshipsBatchQueries):
    """Adapter PostgreSQL pour `AuthorshipsBatchQueries`."""

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)

    def upsert_source_authorships_batch(
        self, conn: Connection, values: list[SourceAuthorshipBatchItem]
    ) -> None:
        upsert_source_authorships_batch(conn, values)

    def fetch_source_authorship_ids_by_position(
        self, conn: Connection, *, source: str, source_publication_id: int, positions: list[int]
    ) -> dict[int, int]:
        return fetch_source_authorship_ids_by_position(
            conn, source=source, source_publication_id=source_publication_id, positions=positions
        )

    def upsert_addresses_batch(self, conn: Connection, values: list[AddressBatchItem]) -> None:
        upsert_addresses_batch(conn, values)

    def fetch_address_ids_by_raw_text(
        self, conn: Connection, raw_texts: list[str]
    ) -> dict[str, int]:
        return fetch_address_ids_by_raw_text(conn, raw_texts)

    def apply_address_countries_batch(
        self, conn: Connection, values: list[AddressCountryItem]
    ) -> None:
        apply_address_countries_batch(conn, values)

    def apply_address_suggested_countries_batch(
        self, conn: Connection, values: list[AddressCountryItem]
    ) -> None:
        apply_address_suggested_countries_batch(conn, values)

    def insert_source_authorship_addresses_batch(
        self, conn: Connection, values: list[AuthorshipAddressItem]
    ) -> None:
        insert_source_authorship_addresses_batch(conn, values)
