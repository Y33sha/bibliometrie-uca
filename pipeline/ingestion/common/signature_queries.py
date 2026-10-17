"""Requêtes d'écriture des signatures (`source_authorships`), des adresses et de leurs liens, communes à toutes les sources.

Les colonnes de `source_authorships` sont identiques pour toutes les sources, seul `source` paramètre l'INSERT. Chaque opération de batch est une **seule** requête : le lot est transmis en JSONB (ou en tableaux parallèles pour le pivot) et étendu côté serveur via `jsonb_to_recordset` / `unnest`.

Consommé par le writer partagé `write_source_authorships`. L'INSERT des `source_authorships` et du pivot reçoit seulement des signatures absentes de la base, ou dont les liens pivot sont supprimés au préalable : il se passe d'`ON CONFLICT`. L'upsert des identités (`author_identifying_keys`, table partagée) et celui des `addresses` gardent leur `ON CONFLICT`.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import NamedTuple, TypedDict

from sqlalchemy import Connection, bindparam, text

from domain.country_detection import CountryDetectionMethod
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from pipeline.transformation.structures.countries.countries_queries import CountryQueries


class SignatureNameFields(TypedDict):
    """Colonnes de nom d'une signature (`signature_name_fields`).

    Sur `source_authorships`, le nom tel que la source le donne : `raw_last_name` et `raw_first_name`, ou `raw_author_name`. Sur l'identité (`author_identifying_keys`), le découpage retenu normalisé.
    """

    raw_author_name: str | None
    raw_last_name: str | None
    raw_first_name: str | None
    last_name_normalized: str
    first_name_normalized: str | None


class SourceAuthorshipItem(SignatureNameFields):
    """Une signature à écrire dans `source_authorships` (toutes sources).

    `person_identifiers` est nullable selon ce que la source fournit.

    `author_position` est nul pour les signatures qui n'occupent pas de rang d'auteur — les rôles non-auteur d'une thèse (direction, rapport, jury, présidence). La contrainte `(source_publication_id, author_position)` les tolère, les `NULL` étant distincts entre eux.
    """

    source: str
    source_publication_id: int
    author_position: int | None
    is_corresponding: bool
    collective: bool
    roles: list[str] | None
    person_identifiers: Mapping[str, JsonValue] | None
    """Lu seulement (sérialisé en JSONB) : `Mapping` accepte les dictionnaires plus étroits que les sources produisent, tel le `dict[str, str]` des identifiants de thèse."""
    neutralized_identifiers: Mapping[str, str] | None
    """Identifiants de `person_identifiers` que la résolution des personnes ignore pour cette signature, avec leur motif (`IdentifierNeutralization`)."""
    content_hash: str | None
    """Empreinte des champs écrits (`signature_content_hash`), adresses comprises."""


class SourceAuthorshipUpdate(SourceAuthorshipItem):
    """Une signature en base, réécrite en place : son identifiant, puis les champs de la signature entrante qui lui est rapprochée."""

    id: int


class StoredSourceAuthorship(NamedTuple):
    """Une signature en base d'une notice : identifiant, position, identité et empreinte."""

    id: int
    author_position: int | None
    last_name_normalized: str | None
    first_name_normalized: str | None
    person_identifiers: JsonValue
    content_hash: str | None


class AddressBatchItem(TypedDict):
    """Ligne du batch upsert `addresses` : forme normalisée, et texte brut d'une adresse nouvelle."""

    raw: str
    norm: str


class AuthorshipAddressItem(TypedDict):
    """Ligne du batch insert `source_authorship_addresses` : pivot (authorship, adresse)."""

    sa_id: int
    addr_id: int


class AuthorshipRorItem(TypedDict):
    """Ligne du batch insert `source_authorship_rors` : ROR attribué par la source à une signature, et adresse de son affiliation (`None` pour une affiliation sans texte)."""

    sa_id: int
    ror_id: str
    addr_id: int | None


# Sentinelles du `key_hash`, alignées sur la colonne générée `author_identifying_keys.key_hash` :
# `E'\x01'` tient lieu de NULL, `E'\x1f'` sépare les champs — des octets de contrôle absents des
# vraies valeurs. Un test d'intégration garde l'alignement avec la colonne générée.
_KEY_HASH_NULL = r"E'\x01'"
_KEY_HASH_SEP = r"E'\x1f'"

# Colonnes de la clé d'identité d'`author_identifying_keys`, dans l'ordre du `key_hash`.
IDENTITY_KEY_COLUMNS = ("last_name_normalized", "first_name_normalized", "person_identifiers")


def key_hash_sql(exprs: Sequence[str]) -> str:
    """Expression SQL du `key_hash` d'une identité, pour le lookup indexé.

    `exprs` : expressions SQL des champs de la clé (colonnes de table ou bind params), dans l'ordre de `IDENTITY_KEY_COLUMNS`.
    """
    parts = [f"coalesce(({e})::text, {_KEY_HASH_NULL})" for e in exprs]
    return "md5(" + f" || {_KEY_HASH_SEP} || ".join(parts) + ")"


_KEY_COLUMNS_SQL = ", ".join(IDENTITY_KEY_COLUMNS)


def delete_orphan_identities(conn: Connection) -> int:
    """Supprime les identités de `author_identifying_keys` que plus aucune signature ne référence.

    Une identité devient orpheline quand la dernière `source_authorships` qui la portait change de clé (nom ou identifiants corrigés) et bascule vers une autre identité. Balayage ensembliste appuyé sur l'index `idx_sa_identity`. Idempotent (no-op si rien n'est orphelin). Retourne le nombre d'identités supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM author_identifying_keys aik
            WHERE NOT EXISTS (
                SELECT 1 FROM source_authorships sa WHERE sa.identity_id = aik.id
            )
        """)
    ).rowcount


def delete_orphan_addresses(conn: Connection) -> int:
    """Supprime les adresses que plus aucune signature ne référence, avec leurs liens aux structures.

    Une adresse devient orpheline quand la dernière signature qui la référençait est réécrite sans elle ou supprimée avec sa notice. Retourne le nombre d'adresses supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM addresses a
            WHERE NOT EXISTS (
                SELECT 1 FROM source_authorship_addresses saa WHERE saa.address_id = a.id
            )
        """)
    ).rowcount


class AuthorshipsBatchQueries:
    """Opérations SQL par lot pour l'écriture des signatures."""

    def upsert_source_authorships_batch(
        self, conn: Connection, values: list[SourceAuthorshipItem]
    ) -> None:
        """L'identité de l'auteur (`IDENTITY_KEY_COLUMNS`) vit sur la table dédupliquée `author_identifying_keys` ; la signature porte seulement une FK `identity_id`. Deux requêtes dans la transaction du writer :

        1. **Upsert des identités du lot** — `INSERT … SELECT DISTINCT … ON CONFLICT DO NOTHING` : les identités du document, dédupliquées, sans churn (un `DO UPDATE` récrirait chaque identité récurrente à chaque document).
        2. **Insert des signatures** — `identity_id` résolu par `key_hash` (colonne générée, index dédié), rapprochement indexé et NULL-safe. Le batch est transmis en JSONB et étendu via `jsonb_to_recordset`. `source`/`source_publication_id`, invariants au sein d'un document, sont hoistés. Les noms normalisés sont fournis pré-calculés (`signature_name_fields`).

        Les deux requêtes restent séquentielles, sans fusion possible : une CTE modifiant `author_identifying_keys` laisserait ses lignes invisibles au JOIN de la même requête (même snapshot). La seconde requête voit celles de la première.
        """
        if not values:
            return
        payload = [
            {
                "author_position": v["author_position"],
                "last_name_normalized": v["last_name_normalized"],
                "first_name_normalized": v["first_name_normalized"],
                "is_corresponding": v["is_corresponding"],
                "collective": v["collective"],
                "roles": v["roles"],
                "raw_author_name": v["raw_author_name"],
                "raw_last_name": v["raw_last_name"],
                "raw_first_name": v["raw_first_name"],
                "person_identifiers": v["person_identifiers"],
                "neutralized_identifiers": v["neutralized_identifiers"],
                "content_hash": v["content_hash"],
            }
            for v in values
        ]
        # 1. Upsert des identités du lot (dédup par clé, sans churn).
        conn.execute(
            text(f"""
                INSERT INTO author_identifying_keys ({_KEY_COLUMNS_SQL})
                SELECT DISTINCT t.last_name_normalized, t.first_name_normalized,
                       t.person_identifiers
                FROM jsonb_to_recordset(:payload) AS t(
                    last_name_normalized text, first_name_normalized text,
                    person_identifiers jsonb)
                ON CONFLICT ({_KEY_COLUMNS_SQL}) DO NOTHING
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        )
        # 2. Insert des signatures. Pas d'ON CONFLICT : le writer DELETE puis déduplique par
        # position, (source_publication_id, author_position) reste unique. `identity_id` résolu
        # par `key_hash` (md5, sentinelles de la colonne générée), lookup indexé.
        stmt = text(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 is_corresponding, collective, roles, raw_author_name, raw_last_name,
                 raw_first_name, identity_id, neutralized_identifiers, content_hash)
            SELECT :source, :spid, t.author_position,
                   t.is_corresponding, t.collective, t.roles, t.raw_author_name, t.raw_last_name,
                   t.raw_first_name, aik.id, t.neutralized_identifiers, t.content_hash
            FROM jsonb_to_recordset(:payload) AS t(
                author_position smallint, last_name_normalized text, first_name_normalized text,
                is_corresponding boolean, collective boolean, roles text[],
                raw_author_name text, raw_last_name text, raw_first_name text,
                person_identifiers jsonb, neutralized_identifiers jsonb, content_hash text)
            JOIN author_identifying_keys aik
              ON aik.key_hash = """
            + key_hash_sql([f"t.{c}" for c in IDENTITY_KEY_COLUMNS])
        ).bindparams(bindparam("payload", type_=Jsonb))
        conn.execute(
            stmt,
            {
                "source": values[0]["source"],
                "spid": values[0]["source_publication_id"],
                "payload": payload,
            },
        )

    def fetch_stored_source_authorships(
        self, conn: Connection, source_publication_id: int
    ) -> list[StoredSourceAuthorship]:
        rows = conn.execute(
            text("""
                SELECT sa.id, sa.author_position, aik.last_name_normalized,
                       aik.first_name_normalized, aik.person_identifiers, sa.content_hash
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.source_publication_id = :spid
            """),
            {"spid": source_publication_id},
        ).all()
        return [StoredSourceAuthorship(*r) for r in rows]

    def delete_source_authorships(self, conn: Connection, ids: list[int]) -> None:
        if ids:
            conn.execute(text("DELETE FROM source_authorships WHERE id = ANY(:ids)"), {"ids": ids})

    def update_source_authorships_batch(
        self, conn: Connection, values: list[SourceAuthorshipUpdate]
    ) -> None:
        # Une seule instruction : la contrainte `(source_publication_id, author_position)`, différable, se vérifie en fin d'instruction, ce qui admet les permutations de positions.
        if not values:
            return
        payload = [
            {
                "id": v["id"],
                "author_position": v["author_position"],
                "is_corresponding": v["is_corresponding"],
                "collective": v["collective"],
                "roles": v["roles"],
                "raw_author_name": v["raw_author_name"],
                "raw_last_name": v["raw_last_name"],
                "raw_first_name": v["raw_first_name"],
                "neutralized_identifiers": v["neutralized_identifiers"],
                "content_hash": v["content_hash"],
            }
            for v in values
        ]
        conn.execute(
            text("""
                UPDATE source_authorships sa
                SET author_position = t.author_position,
                    is_corresponding = t.is_corresponding,
                    collective = t.collective,
                    roles = t.roles,
                    raw_author_name = t.raw_author_name,
                    raw_last_name = t.raw_last_name,
                    raw_first_name = t.raw_first_name,
                    neutralized_identifiers = t.neutralized_identifiers,
                    content_hash = t.content_hash,
                    countries_dirty = true
                FROM jsonb_to_recordset(:payload) AS t(
                    id integer, author_position smallint, is_corresponding boolean,
                    collective boolean, roles text[], raw_author_name text, raw_last_name text,
                    raw_first_name text, neutralized_identifiers jsonb, content_hash text)
                WHERE sa.id = t.id
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        )

    def fetch_authors_hash(self, conn: Connection, source_publication_id: int) -> str | None:
        return conn.execute(
            text("SELECT authors_hash FROM source_publications WHERE id = :id"),
            {"id": source_publication_id},
        ).scalar_one_or_none()

    def set_authors_hash(
        self, conn: Connection, source_publication_id: int, authors_hash: str
    ) -> None:
        conn.execute(
            text("UPDATE source_publications SET authors_hash = :h WHERE id = :id"),
            {"h": authors_hash, "id": source_publication_id},
        )

    def delete_source_authorship_addresses(self, conn: Connection, ids: list[int]) -> None:
        if ids:
            conn.execute(
                text(
                    "DELETE FROM source_authorship_addresses WHERE source_authorship_id = ANY(:ids)"
                ),
                {"ids": ids},
            )

    def delete_source_authorship_rors(self, conn: Connection, ids: list[int]) -> None:
        if ids:
            conn.execute(
                text("DELETE FROM source_authorship_rors WHERE source_authorship_id = ANY(:ids)"),
                {"ids": ids},
            )

    def delete_source_authorship_hal_structures(self, conn: Connection, ids: list[int]) -> None:
        if ids:
            conn.execute(
                text(
                    "DELETE FROM source_authorship_hal_structures"
                    " WHERE source_authorship_id = ANY(:ids)"
                ),
                {"ids": ids},
            )

    def upsert_addresses_batch(self, conn: Connection, values: list[AddressBatchItem]) -> None:
        if not values:
            return
        stmt = text("""
            INSERT INTO addresses (raw_text, normalized_text)
            SELECT t.raw, t.norm
            FROM jsonb_to_recordset(:payload) AS t(raw text, norm text)
            ON CONFLICT (md5(normalized_text)) DO NOTHING
        """).bindparams(bindparam("payload", type_=Jsonb))
        conn.execute(stmt, {"payload": list(values)})

    def fetch_address_ids_by_normalized_text(
        self, conn: Connection, normalized_texts: list[str]
    ) -> dict[str, int]:
        """Identifiant de l'adresse de chaque forme normalisée. Le filtre sur `md5(normalized_text)` passe par l'index unique `addresses_normalized_text_key`, qui sert aussi le `ON CONFLICT` de `upsert_addresses_batch`. `md5()` PostgreSQL et `hashlib.md5` sur l'UTF-8 coïncident."""
        if not normalized_texts:
            return {}
        md5s = [
            hashlib.md5(t.encode(), usedforsecurity=False).hexdigest() for t in normalized_texts
        ]
        rows = conn.execute(
            text(
                "SELECT normalized_text, id FROM addresses WHERE md5(normalized_text) = ANY(:md5s)"
            ),
            {"md5s": md5s},
        ).all()
        return {r.normalized_text: r.id for r in rows}

    def insert_address_country_candidates(
        self,
        conn: Connection,
        method: CountryDetectionMethod,
        rows: list[tuple[int, list[str]]],
    ) -> None:
        """Ajoute les pays candidats `(adresse, pays)` du moyen `method` (`CountryQueries.insert_candidates`)."""
        CountryQueries().insert_candidates(conn, method, rows)

    def insert_source_authorship_addresses_batch(
        self, conn: Connection, values: list[AuthorshipAddressItem]
    ) -> None:
        # Pas d'ON CONFLICT : le writer supprime les liens d'une signature réécrite avant de les réinsérer, et déduplique les couples (sa_id, addr_id).
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

    def insert_source_authorship_hal_structures_batch(
        self, conn: Connection, values: list[tuple[int, int]]
    ) -> None:
        """Écrit les couples (signature, structure HAL). Le writer supprime d'abord ceux d'une signature réécrite."""
        if not values:
            return
        conn.execute(
            text("""
                INSERT INTO source_authorship_hal_structures (source_authorship_id, hal_structure_id)
                SELECT sa_id, hal_structure_id
                FROM unnest(:sa_ids ::integer[], :hal_structure_ids ::integer[]) AS t(sa_id, hal_structure_id)
            """),
            {
                "sa_ids": [sa_id for sa_id, _ in values],
                "hal_structure_ids": [hal_id for _, hal_id in values],
            },
        )

    def insert_source_authorship_rors_batch(
        self, conn: Connection, values: list[AuthorshipRorItem]
    ) -> None:
        # Pas d'ON CONFLICT : le writer supprime les ROR d'une signature réécrite avant de les réinsérer, et les ROR d'une signature forment un ensemble.
        if not values:
            return
        conn.execute(
            text("""
                INSERT INTO source_authorship_rors (source_authorship_id, ror_id, address_id)
                SELECT sa_id, ror_id, addr_id
                FROM unnest(:sa_ids ::integer[], :ror_ids ::text[], :addr_ids ::integer[])
                    AS t(sa_id, ror_id, addr_id)
            """),
            {
                "sa_ids": [v["sa_id"] for v in values],
                "ror_ids": [v["ror_id"] for v in values],
                "addr_ids": [v["addr_id"] for v in values],
            },
        )
