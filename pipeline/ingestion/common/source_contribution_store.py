"""Écriture par lot des contributions sources, des informations du contributeur, des adresses et de leurs liens, commune à toutes les sources.

Chaque opération de lot est une seule requête : le lot passe en JSONB, ou en tableaux parallèles, et s'étend côté serveur (`jsonb_to_recordset`, `unnest`). `write_source_contributions` supprime les liens d'une contribution source réécrite avant de les réinsérer : les insertions de contributions sources et de liens se passent d'`ON CONFLICT`. Les informations du contributeur et les adresses, partagées, gardent le leur.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import NamedTuple, TypedDict

from sqlalchemy import Connection, bindparam, text

from domain.country_detection import CountryDetectionMethod
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue, enqueue_sql
from pipeline.transformation.countries.store import CountryCandidatesStore


class ContributorNameFields(TypedDict):
    """Colonnes de nom d'une contribution source (`contributor_name_fields`).

    Sur `source_contributions`, le nom tel que la source le donne : `raw_last_name` et `raw_first_name`, ou `raw_author_name`. Sur les informations du contributeur (`contributor_information`), le découpage retenu normalisé.
    """

    raw_author_name: str | None
    raw_last_name: str | None
    raw_first_name: str | None
    last_name_normalized: str
    first_name_normalized: str | None


class SourceContributionItem(ContributorNameFields):
    """Une contribution source à écrire.

    Une contribution source sans rang d'auteur (direction, rapport, jury ou présidence d'une thèse) a une position nulle. La contrainte d'unicité de la position la tolère : deux `NULL` sont distincts.
    """

    source: str
    source_record_id: int
    author_position: int | None
    is_corresponding: bool
    collective: bool
    roles: Sequence[str] | None
    identifiers: Mapping[str, JsonValue] | None
    """Lu seulement (sérialisé en JSONB) : `Mapping` accepte les dictionnaires plus étroits que les sources produisent, tel le `dict[str, str]` des identifiants de thèse."""
    neutralized_identifiers: Mapping[str, str] | None
    """Identifiants de `identifiers` que la résolution des personnes ignore pour cette contribution source, avec leur motif (`IdentifierNeutralization`)."""
    content_hash: str | None
    """Empreinte des champs écrits (`signature_content_hash`), adresses comprises."""


class SourceContributionUpdate(SourceContributionItem):
    """Une contribution source en base, réécrite en place : son identifiant, puis les champs de la contribution source entrante qui lui est rapprochée."""

    id: int


class StoredSourceContributionRow(NamedTuple):
    """Une contribution source en base d'un enregistrement source : identifiant, position, informations du contributeur, empreinte, marque collective et rôles."""

    id: int
    author_position: int | None
    last_name_normalized: str | None
    first_name_normalized: str | None
    identifiers: JsonValue
    content_hash: str | None
    collective: bool
    roles: list[str] | None


class AddressBatchItem(TypedDict):
    """Adresse d'un lot à écrire : forme normalisée, et texte brut d'une adresse nouvelle."""

    raw: str
    norm: str


class ContributionAddressItem(TypedDict):
    """Lien d'un lot entre une contribution source et une adresse."""

    source_contribution_id: int
    addr_id: int


class ContributionRorItem(TypedDict):
    """ROR d'un lot, attribué par la source à une contribution source, avec l'adresse de son affiliation (`None` pour une affiliation sans texte)."""

    source_contribution_id: int
    ror_id: str
    addr_id: int | None


# Sentinelles du `key_hash`, alignées sur la colonne générée `contributor_information.key_hash` : `E'\x01'` tient lieu de NULL, `E'\x1f'` sépare les champs. Ces octets de contrôle sont absents des vraies valeurs.
# Un test d'intégration garde l'alignement avec la colonne générée.
_KEY_HASH_NULL = r"E'\x01'"
_KEY_HASH_SEP = r"E'\x1f'"

# Colonnes de la clé de `contributor_information`, dans l'ordre du `key_hash`.
CONTRIBUTOR_INFORMATION_KEY_COLUMNS = (
    "last_name_normalized",
    "first_name_normalized",
    "identifiers",
)


def key_hash_sql(exprs: Sequence[str]) -> str:
    """Expression SQL du `key_hash` d'une ligne de `contributor_information`, pour la recherche par l'index.

    Les expressions SQL des champs de la clé (colonnes ou paramètres liés) suivent l'ordre de `CONTRIBUTOR_INFORMATION_KEY_COLUMNS`.
    """
    parts = [f"coalesce(({e})::text, {_KEY_HASH_NULL})" for e in exprs]
    return "md5(" + f" || {_KEY_HASH_SEP} || ".join(parts) + ")"


_KEY_COLUMNS_SQL = ", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)

# Marque les contributions des contributions sources de la CTE `updated(id, attributes_changed)` dont les rôles ou le statut de correspondant changent.
_MARK_CONTRIBUTIONS_OF_UPDATED = enqueue_sql(
    Queue.CONTRIBUTION_ATTRIBUTES,
    """
    SELECT gm.contribution_id FROM aligned_source_contributions gm
    JOIN updated u ON u.id = gm.source_contribution_id
    WHERE u.attributes_changed
    """,
)


def mark_source_contributions_to_resync(conn: Connection, source: str) -> int:
    """Vide l'empreinte du bloc auteurs des enregistrements sources de `source` : leur prochaine normalisation synchronise leurs contributions sources. Rend le nombre d'enregistrements sources marqués."""
    return conn.execute(
        text("""
            UPDATE source_records SET authors_hash = NULL
            WHERE source = :source AND authors_hash IS NOT NULL
        """),
        {"source": source},
    ).rowcount


def delete_orphan_contributor_information(conn: Connection) -> int:
    """Supprime les lignes de `contributor_information` qu'aucune contribution source ne référence.

    Une ligne devient orpheline quand la dernière contribution source qui la référençait change de clé (nom ou identifiants corrigés) et passe à une autre ligne. Rend le nombre de lignes supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM contributor_information ci
            WHERE NOT EXISTS (
                SELECT 1 FROM source_contributions sc WHERE sc.contributor_information_id = ci.id
            )
        """)
    ).rowcount


def delete_orphan_addresses(conn: Connection) -> int:
    """Supprime les adresses qu'aucune contribution source ne référence, avec leurs liens aux structures.

    Une adresse devient orpheline quand la dernière contribution source qui la référençait est réécrite sans elle ou supprimée avec son enregistrement source. Rend le nombre d'adresses supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM addresses a
            WHERE NOT EXISTS (
                SELECT 1 FROM source_contribution_addresses sca WHERE sca.address_id = a.id
            )
        """)
    ).rowcount


class SourceContributionStore:
    """Écriture par lot des contributions sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert_source_contributions_batch(self, values: list[SourceContributionItem]) -> None:
        """Insère les contributions sources d'un enregistrement source, et les informations du contributeur qui leur manquent.

        Les informations du contributeur sont dans `contributor_information`, sans doublon ; la contribution source y renvoie. Une première requête insère celles du lot qui manquent. La seconde insère les contributions sources, rattachées par `key_hash`. Les deux requêtes restent distinctes : une CTE qui écrit dans `contributor_information` laisse ses lignes invisibles au JOIN de la même requête.
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
                "identifiers": v["identifiers"],
                "neutralized_identifiers": v["neutralized_identifiers"],
                "content_hash": v["content_hash"],
            }
            for v in values
        ]
        # Informations du contributeur du lot qui manquent. Un `DO UPDATE` réécrirait à chaque enregistrement source les lignes qui reviennent.
        self._conn.execute(
            text(f"""
                INSERT INTO contributor_information ({_KEY_COLUMNS_SQL})
                SELECT DISTINCT t.last_name_normalized, t.first_name_normalized,
                       t.identifiers
                FROM jsonb_to_recordset(:payload) AS t(
                    last_name_normalized text, first_name_normalized text,
                    identifiers jsonb)
                ON CONFLICT ({_KEY_COLUMNS_SQL}) DO NOTHING
            """).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        )
        # Contributions sources, marquées pour le recalcul des pays. `write_source_contributions` supprime puis déduplique par position : l'insertion se passe d'`ON CONFLICT`.
        stmt = text(
            """
            WITH inserted AS (
            INSERT INTO source_contributions
                (source, source_record_id, author_position,
                 is_corresponding, collective, roles, raw_author_name, raw_last_name,
                 raw_first_name, contributor_information_id, neutralized_identifiers, content_hash)
            SELECT :source, :spid, t.author_position,
                   t.is_corresponding, t.collective, t.roles, t.raw_author_name, t.raw_last_name,
                   t.raw_first_name, ci.id, t.neutralized_identifiers, t.content_hash
            FROM jsonb_to_recordset(:payload) AS t(
                author_position smallint, last_name_normalized text, first_name_normalized text,
                is_corresponding boolean, collective boolean, roles text[],
                raw_author_name text, raw_last_name text, raw_first_name text,
                identifiers jsonb, neutralized_identifiers jsonb, content_hash text)
            JOIN contributor_information ci
              ON ci.key_hash = """
            + key_hash_sql([f"t.{c}" for c in CONTRIBUTOR_INFORMATION_KEY_COLUMNS])
            + " RETURNING id) "
            + enqueue_sql(Queue.SOURCE_CONTRIBUTION_COUNTRIES, "SELECT id FROM inserted")
        ).bindparams(bindparam("payload", type_=Jsonb))
        self._conn.execute(
            stmt,
            {
                "source": values[0]["source"],
                "spid": values[0]["source_record_id"],
                "payload": payload,
            },
        )

    def fetch_stored_source_contributions(
        self, source_record_id: int
    ) -> list[StoredSourceContributionRow]:
        rows = self._conn.execute(
            text("""
                SELECT sc.id, sc.author_position, ci.last_name_normalized,
                       ci.first_name_normalized, ci.identifiers, sc.content_hash,
                       sc.collective, sc.roles
                FROM source_contributions sc
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sc.source_record_id = :spid
            """),
            {"spid": source_record_id},
        ).all()
        return [StoredSourceContributionRow(*r) for r in rows]

    def mark_publication_for_grouping(self, source_record_id: int) -> None:
        """Marque la publication de l'enregistrement source pour le groupement des auteurs."""
        enqueue(
            self._conn,
            Queue.PUBLICATION_CONTRIBUTIONS,
            "SELECT publication_id FROM source_records WHERE id = :spid AND publication_id IS NOT NULL",
            {"spid": source_record_id},
        )

    def delete_source_contributions(self, ids: list[int]) -> None:
        if ids:
            self._conn.execute(
                text("DELETE FROM source_contributions WHERE id = ANY(:ids)"), {"ids": ids}
            )

    def update_source_contributions_batch(self, values: list[SourceContributionUpdate]) -> None:
        """Réécrit en place des contributions sources. Les marque pour le recalcul des pays, et marque les contributions de celles dont les rôles ou le statut de correspondant changent."""
        # Une seule instruction : la contrainte `(source_record_id, author_position)`, différable, se vérifie en fin d'instruction, ce qui admet les permutations de positions.
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
        self._conn.execute(
            text(
                """
                WITH updated AS (
                UPDATE source_contributions sc
                SET author_position = t.author_position,
                    is_corresponding = t.is_corresponding,
                    collective = t.collective,
                    roles = t.roles,
                    raw_author_name = t.raw_author_name,
                    raw_last_name = t.raw_last_name,
                    raw_first_name = t.raw_first_name,
                    neutralized_identifiers = t.neutralized_identifiers,
                    content_hash = t.content_hash
                FROM jsonb_to_recordset(:payload) AS t(
                    id integer, author_position smallint, is_corresponding boolean,
                    collective boolean, roles text[], raw_author_name text, raw_last_name text,
                    raw_first_name text, neutralized_identifiers jsonb, content_hash text)
                WHERE sc.id = t.id
                RETURNING sc.id,
                    (old.is_corresponding, old.roles) IS DISTINCT FROM (new.is_corresponding, new.roles)
                        AS attributes_changed
                ),
                marked_contributions AS ("""
                + _MARK_CONTRIBUTIONS_OF_UPDATED
                + ")"
                + enqueue_sql(Queue.SOURCE_CONTRIBUTION_COUNTRIES, "SELECT id FROM updated")
            ).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        )

    def set_author_counts(self, source_record_id: int, author_count: int, distinct: int) -> None:
        """Écrit `author_count` et `distinct_author_count` de l'enregistrement source."""
        self._conn.execute(
            text("""
                UPDATE source_records
                SET author_count = :n, distinct_author_count = :d
                WHERE id = :id AND (author_count, distinct_author_count) IS DISTINCT FROM (:n, :d)
            """),
            {"n": author_count, "d": distinct, "id": source_record_id},
        )

    def fetch_authors_hash(self, source_record_id: int) -> str | None:
        return self._conn.execute(
            text("SELECT authors_hash FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).scalar_one_or_none()

    def set_authors_hash(self, source_record_id: int, authors_hash: str) -> None:
        self._conn.execute(
            text("UPDATE source_records SET authors_hash = :h WHERE id = :id"),
            {"h": authors_hash, "id": source_record_id},
        )

    def delete_source_contribution_addresses(self, ids: list[int]) -> None:
        if ids:
            self._conn.execute(
                text(
                    "DELETE FROM source_contribution_addresses WHERE source_contribution_id = ANY(:ids)"
                ),
                {"ids": ids},
            )

    def delete_source_contribution_rors(self, ids: list[int]) -> None:
        if ids:
            self._conn.execute(
                text(
                    "DELETE FROM source_contribution_rors WHERE source_contribution_id = ANY(:ids)"
                ),
                {"ids": ids},
            )

    def delete_source_contribution_hal_structures(self, ids: list[int]) -> None:
        if ids:
            self._conn.execute(
                text(
                    "DELETE FROM source_contribution_hal_structures"
                    " WHERE source_contribution_id = ANY(:ids)"
                ),
                {"ids": ids},
            )

    def upsert_addresses_batch(self, values: list[AddressBatchItem]) -> None:
        """Crée les adresses absentes de la base, et les marque pour la détection de leur pays."""
        if not values:
            return
        stmt = text(
            """
            WITH inserted AS (
                INSERT INTO addresses (raw_text, normalized_text)
                SELECT t.raw, t.norm
                FROM jsonb_to_recordset(:payload) AS t(raw text, norm text)
                ON CONFLICT (md5(normalized_text)) DO NOTHING
                RETURNING id
            )
            """
            + enqueue_sql(Queue.ADDRESS_CANDIDATES, "SELECT id FROM inserted")
        ).bindparams(bindparam("payload", type_=Jsonb))
        self._conn.execute(stmt, {"payload": list(values)})

    def fetch_address_ids_by_normalized_text(self, normalized_texts: list[str]) -> dict[str, int]:
        """Identifiant de l'adresse de chaque forme normalisée. La recherche passe par `md5(normalized_text)`, clé de l'index unique des adresses ; le `md5` de PostgreSQL et celui de `hashlib` coïncident sur l'UTF-8."""
        if not normalized_texts:
            return {}
        md5s = [
            hashlib.md5(t.encode(), usedforsecurity=False).hexdigest() for t in normalized_texts
        ]
        rows = self._conn.execute(
            text(
                "SELECT normalized_text, id FROM addresses WHERE md5(normalized_text) = ANY(:md5s)"
            ),
            {"md5s": md5s},
        ).all()
        return {r.normalized_text: r.id for r in rows}

    def insert_address_country_candidates(
        self,
        method: CountryDetectionMethod,
        rows: list[tuple[int, list[str]]],
    ) -> None:
        """Ajoute aux adresses leurs pays candidats, pour un moyen de détection."""
        CountryCandidatesStore(self._conn).add(method, rows)

    def insert_source_contribution_addresses_batch(
        self, values: list[ContributionAddressItem]
    ) -> None:
        # `write_source_contributions` supprime les liens d'une contribution source réécrite avant de les réinsérer, et déduplique les couples : l'insertion se passe d'`ON CONFLICT`.
        if not values:
            return
        stmt = text("""
            INSERT INTO source_contribution_addresses (source_contribution_id, address_id)
            SELECT source_contribution_id, addr_id
            FROM unnest(:source_contribution_ids ::integer[], :addr_ids ::integer[]) AS t(source_contribution_id, addr_id)
        """)
        self._conn.execute(
            stmt,
            {
                "source_contribution_ids": [v["source_contribution_id"] for v in values],
                "addr_ids": [v["addr_id"] for v in values],
            },
        )

    def insert_source_contribution_hal_structures_batch(
        self, values: list[tuple[int, int]]
    ) -> None:
        """Écrit les liens entre contributions sources et structures HAL. `write_source_contributions` supprime d'abord ceux d'une contribution source réécrite."""
        if not values:
            return
        self._conn.execute(
            text("""
                INSERT INTO source_contribution_hal_structures (source_contribution_id, hal_structure_id)
                SELECT source_contribution_id, hal_structure_id
                FROM unnest(:source_contribution_ids ::integer[], :hal_structure_ids ::integer[]) AS t(source_contribution_id, hal_structure_id)
            """),
            {
                "source_contribution_ids": [
                    source_contribution_id for source_contribution_id, _ in values
                ],
                "hal_structure_ids": [hal_id for _, hal_id in values],
            },
        )

    def insert_source_contribution_rors_batch(self, values: list[ContributionRorItem]) -> None:
        # `write_source_contributions` supprime les ROR d'une contribution source réécrite avant de les réinsérer, et les ROR d'une contribution source sont sans doublon : l'insertion se passe d'`ON CONFLICT`.
        if not values:
            return
        self._conn.execute(
            text("""
                INSERT INTO source_contribution_rors (source_contribution_id, ror_id, address_id)
                SELECT source_contribution_id, ror_id, addr_id
                FROM unnest(:source_contribution_ids ::integer[], :ror_ids ::text[], :addr_ids ::integer[])
                    AS t(source_contribution_id, ror_id, addr_id)
            """),
            {
                "source_contribution_ids": [v["source_contribution_id"] for v in values],
                "ror_ids": [v["ror_id"] for v in values],
                "addr_ids": [v["addr_id"] for v in values],
            },
        )
