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
ne préexiste — d'où l'absence d'`ON CONFLICT` sur l'INSERT des `source_authorships`
et du pivot. L'upsert des identités (`author_identifying_keys`, table partagée non
vidée) et celui des `addresses` conservent leur `ON CONFLICT`.
"""

import hashlib

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.authorships import (
    AddressBatchItem,
    AddressCountryItem,
    AuthorshipAddressItem,
    AuthorshipsBatchQueries,
    SourceAuthorshipItem,
)
from infrastructure.queries.pipeline.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_source_authorships_batch(conn: Connection, values: list[SourceAuthorshipItem]) -> None:
    """Batch UPSERT de `source_authorships` (toutes sources, `source` par ligne).

    L'identité de l'auteur (`author_name_normalized`, `person_identifiers`) vit sur
    la table dédupliquée `author_identifying_keys` ; la signature ne porte qu'une
    FK `identity_id`. Deux requêtes dans la transaction du writer :

    1. **Upsert des identités du lot** — `INSERT … SELECT DISTINCT … ON CONFLICT
       DO NOTHING` : les identités du document, dédupliquées, sans churn (un
       `DO UPDATE` récrirait chaque identité récurrente à chaque document).
    2. **Insert des signatures** — `identity_id` résolu par `key_hash` (colonne
       générée, index dédié), rapprochement indexé et NULL-safe. Le batch est
       transmis en JSONB et étendu via `jsonb_to_recordset` (vs un `executemany`
       en N allers-retours). `source`/`source_publication_id` sont invariants au
       sein d'un document, donc hoistés. Le nom normalisé est fourni pré-calculé
       (`author_name_normalized`, via `normalize_name_form` côté Python).

    Les deux requêtes sont séquentielles et non fusionnables : une CTE modifiant
    `author_identifying_keys` ne rendrait pas ses lignes visibles au JOIN de la
    même requête (même snapshot). La seconde requête voit celles de la première.
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
    # 1. Upsert des identités du lot (dédup par clé, sans churn).
    conn.execute(
        text("""
            INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
            SELECT DISTINCT t.author_name_normalized, t.person_identifiers
            FROM jsonb_to_recordset(:payload) AS t(
                author_name_normalized text, person_identifiers jsonb)
            ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING
        """).bindparams(bindparam("payload", type_=JSONB)),
        {"payload": payload},
    )
    # 2. Insert des signatures. Pas d'ON CONFLICT : le writer DELETE avant d'insérer
    # (clear) et déduplique par position, donc (source_publication_id, author_position)
    # ne peut pas entrer en collision. `identity_id` résolu par `key_hash` : md5 de la
    # clé d'identité, mêmes sentinelles que la colonne générée (E'\x01' pour NULL,
    # E'\x1f' séparateur) — lookup indexé, NULL-safe.
    stmt = text(r"""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position,
             is_corresponding, roles, raw_author_name, identity_id)
        SELECT :source, :spid, t.author_position,
               t.is_corresponding, t.roles, t.raw_author_name, aik.id
        FROM jsonb_to_recordset(:payload) AS t(
            author_position smallint, author_name_normalized text,
            is_corresponding boolean, roles text[],
            raw_author_name text, person_identifiers jsonb)
        JOIN author_identifying_keys aik
          ON aik.key_hash = md5(
                 coalesce(t.author_name_normalized, E'\x01') || E'\x1f'
                 || coalesce(t.person_identifiers::text, E'\x01'))
    """).bindparams(bindparam("payload", type_=JSONB))
    conn.execute(
        stmt,
        {
            "source": values[0]["source"],
            "spid": values[0]["source_publication_id"],
            "payload": payload,
        },
    )


_UPSERT_IDENTITY_SQL = text("""
    INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
    VALUES (:author_name_normalized, :person_identifiers)
    ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING
""").bindparams(bindparam("person_identifiers", type_=JSONB))

_INSERT_AUTHORSHIP_SQL = text(r"""
    INSERT INTO source_authorships
        (source, source_publication_id, author_position,
         is_corresponding, roles, raw_author_name, identity_id)
    VALUES (:source, :source_publication_id, :author_position,
            :is_corresponding, :roles, :raw_author_name,
            (SELECT id FROM author_identifying_keys
             WHERE key_hash = md5(
                 coalesce(:author_name_normalized, E'\x01') || E'\x1f'
                 || coalesce((:person_identifiers)::text, E'\x01'))))
    RETURNING id
""").bindparams(bindparam("person_identifiers", type_=JSONB))


def upsert_source_authorship(conn: Connection, item: SourceAuthorshipItem) -> int:
    """Écrit une signature seule et retourne son id.

    Même mécanisme que le batch — upsert de l'identité, puis résolution de `identity_id`
    par `key_hash` — pour une seule ligne, dont l'id est rendu par `RETURNING`. Sert les
    signatures sans rang d'auteur, que le remap par position du writer batch ne sait pas
    retrouver. Pas d'`ON CONFLICT`, pour la même raison que le batch : le `clear` en amont
    vide le document.
    """
    conn.execute(_UPSERT_IDENTITY_SQL, dict(item))
    return conn.execute(_INSERT_AUTHORSHIP_SQL, dict(item)).one().id


def delete_orphan_identities(conn: Connection) -> int:
    """Supprime les identités de `author_identifying_keys` que plus aucune signature ne référence.

    Une identité devient orpheline quand la dernière `source_authorships` qui la portait change
    de clé (nom ou identifiants corrigés) et bascule vers une autre identité. Balayage ensembliste
    appuyé sur l'index `idx_sa_identity`. Idempotent (no-op si rien n'est orphelin). Retourne le
    nombre d'identités supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM author_identifying_keys aik
            WHERE NOT EXISTS (
                SELECT 1 FROM source_authorships sa WHERE sa.identity_id = aik.id
            )
        """)
    ).rowcount


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

    def upsert_source_authorship(self, conn: Connection, item: SourceAuthorshipItem) -> int:
        return upsert_source_authorship(conn, item)

    def upsert_source_authorships_batch(
        self, conn: Connection, values: list[SourceAuthorshipItem]
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
