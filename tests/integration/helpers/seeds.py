"""Semis de données pour les tests d'API, sur le pool propriétaire (`owner_pool`).

Chaque fonction insère une ligne, valeurs par défaut uniques quand la table l'exige, et renvoie son `id`.
"""

import json
import uuid

from tests.integration.helpers.authorships import upsert_identity_on_cursor
from tests.integration.helpers.db import owner_pool


def uniq(prefix: str, sep: str = "_") -> str:
    """`prefix` suivi d'un suffixe aléatoire de 8 caractères hexadécimaux."""
    return f"{prefix}{sep}{uuid.uuid4().hex[:8]}"


def _insert(sql: str, params: tuple) -> int:
    with owner_pool() as cur:
        cur.execute(sql, params)
        return cur.fetchone()["id"]


def seed_address(raw_text: str, *, countries: list[str] | None = None, pub_count: int = 1) -> int:
    return _insert(
        "INSERT INTO addresses (raw_text, normalized_text, countries, pub_count) "
        "VALUES (%s, lower(%s), %s, %s) RETURNING id",
        (raw_text, raw_text, countries, pub_count),
    )


def seed_structure(code: str | None = None, type_: str = "labo") -> int:
    code = code or uniq("STR")
    return _insert(
        "INSERT INTO structures (code, name, structure_type) "
        "VALUES (%s, %s, CAST(%s AS structure_type)) RETURNING id",
        (code, code, type_),
    )


def seed_structure_name_form(structure_id: int, form_text: str | None = None) -> int:
    """Forme de nom de structure ; une forme de 6 caractères au plus est en mots entiers, comme l'exige la table."""
    form_text = form_text or uniq("form")
    return _insert(
        "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
        "VALUES (%s, %s, char_length(%s) <= 6) RETURNING id",
        (structure_id, form_text, form_text),
    )


def seed_perimeter(
    code: str | None = None, root_structure_ids: list[int] | None = None, name: str | None = None
) -> int:
    code = code or uniq("perim")
    return _insert(
        "INSERT INTO perimeters (code, name, root_structure_ids) VALUES (%s, %s, %s) RETURNING id",
        (code, name or code, root_structure_ids or []),
    )


def seed_publisher(name: str | None = None) -> int:
    name = name or uniq("Publisher")
    return _insert(
        "INSERT INTO publishers (name, name_normalized) "
        "VALUES (%s, normalize_name_form(%s)) RETURNING id",
        (name, name),
    )


def seed_journal(title: str | None = None, publisher_id: int | None = None) -> int:
    title = title or uniq("Journal")
    return _insert(
        "INSERT INTO journals (title, title_normalized, publisher_id) "
        "VALUES (%s, normalize_name_form(%s), %s) RETURNING id",
        (title, title, publisher_id),
    )


def seed_person(last: str = "TEST", first: str = "J") -> int:
    return _insert(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
        (last, first, last, first),
    )


def seed_publication(title: str = "T", year: int = 2024) -> int:
    return _insert(
        "INSERT INTO publications (title, title_normalized, pub_year) "
        "VALUES (%s, lower(%s), %s) RETURNING id",
        (title, title, year),
    )


def seed_source_publication(
    source: str = "hal",
    *,
    source_id: str | None = None,
    title: str = "T",
    pub_year: int | None = 2024,
    publication_id: int | None = None,
    journal_id: int | None = None,
    doc_type: str | None = None,
    doi: str | None = None,
    raw_metadata: dict[str, object] | None = None,
) -> int:
    """Notice d'identifiant `source_id`, unique par défaut. Une colonne à `None` garde la valeur par défaut du schéma."""
    values = {
        "source": source,
        "source_id": source_id or uniq("sid"),
        "title": title,
        "pub_year": pub_year,
        "publication_id": publication_id,
        "journal_id": journal_id,
        "doc_type": doc_type,
        "doi": doi,
        "raw_metadata": json.dumps(raw_metadata) if raw_metadata is not None else None,
    }
    values = {column: value for column, value in values.items() if value is not None}
    placeholders = ["CAST(%s AS jsonb)" if column == "raw_metadata" else "%s" for column in values]
    return _insert(
        f"INSERT INTO source_publications ({', '.join(values)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING id",
        tuple(values.values()),
    )


def seed_source_authorship(
    source: str = "hal",
    source_pub_id: int | None = None,
    person_id: int | None = None,
    authorship_id: int | None = None,
    in_perimeter: bool = True,
    raw_author_name: str = "Test Author",
    author_position: int = 0,
) -> int:
    """Signature de nom brut `raw_author_name`, sur une notice semée au besoin."""
    sp = source_pub_id or seed_source_publication(source=source)
    with owner_pool() as cur:
        iid = upsert_identity_on_cursor(cur, raw_author_name.lower())
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, authorship_id, in_perimeter, raw_author_name, identity_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                source,
                sp,
                author_position,
                person_id,
                authorship_id,
                in_perimeter,
                raw_author_name,
                iid,
            ),
        )
        return cur.fetchone()["id"]
