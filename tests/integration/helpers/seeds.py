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


def seed_publisher(name: str | None = None, *, name_normalized: str | None = None) -> int:
    """Éditeur de nom unique par défaut, normalisé par `normalize_name_form` sauf `name_normalized`."""
    name = name or uniq("Publisher")
    return _insert(
        "INSERT INTO publishers (name, name_normalized) "
        "VALUES (%s, COALESCE(%s, normalize_name_form(%s))) RETURNING id",
        (name, name_normalized, name),
    )


def seed_journal(
    title: str | None = None,
    *,
    title_normalized: str | None = None,
    publisher_id: int | None = None,
    journal_type: str = "unknown",
) -> int:
    """Revue de titre unique par défaut, normalisé par `normalize_name_form` sauf `title_normalized`. Le type par défaut est celui du schéma."""
    title = title or uniq("Journal")
    return _insert(
        "INSERT INTO journals (title, title_normalized, publisher_id, journal_type) "
        "VALUES (%s, COALESCE(%s, normalize_name_form(%s)), %s, CAST(%s AS journal_type)) "
        "RETURNING id",
        (title, title_normalized, title, publisher_id, journal_type),
    )


def seed_journal_issn(
    journal_id: int,
    *,
    issn: str,
    support: str | None = None,
    linking: bool = False,
    status: str = "active",
) -> int:
    """ISSN de la revue `journal_id`. Les valeurs par défaut sont celles du schéma."""
    return _insert(
        "INSERT INTO journal_issns (issn, journal_id, support, linking, status) "
        "VALUES (%s, %s, CAST(%s AS issn_support), %s, CAST(%s AS issn_status)) RETURNING id",
        (issn, journal_id, support, linking, status),
    )


def seed_monograph(title: str, *, proceedings: bool = False, isbn: str | None = None) -> int:
    """Monographie de titre normalisé par `normalize_name_form`."""
    return _insert(
        "INSERT INTO monographs (title, title_normalized, proceedings, isbn)"
        " VALUES (%s, normalize_name_form(%s), %s, %s) RETURNING id",
        (title, title, proceedings, isbn),
    )


def seed_person(
    last: str = "TEST",
    first: str = "J",
    *,
    normalizer: str = "lower",
    first_name_normalized: str | None = None,
) -> int:
    """Personne aux nom et prénom normalisés par la fonction SQL `normalizer` (`lower` ou `normalize_name_form`). `first_name_normalized` impose le prénom normalisé."""
    assert normalizer in ("lower", "normalize_name_form"), normalizer
    return _insert(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        f"VALUES (%s, %s, {normalizer}(%s), COALESCE(%s, {normalizer}(%s))) RETURNING id",
        (last, first, last, first_name_normalized, first),
    )


def seed_person_identifier(
    person_id: int, *, id_type: str, id_value: str, source: str = "manual", status: str = "pending"
) -> int:
    """Identifiant de la personne `person_id`. Le statut par défaut est celui du schéma."""
    return _insert(
        "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
        "VALUES (%s, %s, %s, CAST(%s AS identifier_origin), CAST(%s AS identifier_status)) "
        "RETURNING id",
        (person_id, id_type, id_value, source, status),
    )


def seed_person_name_form(person_id: int, *, name_form: str, sources: list[str]) -> None:
    """Forme de nom de la personne `person_id`."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO person_name_forms (name_form, person_id, sources) VALUES (%s, %s, %s)",
            (name_form, person_id, sources),
        )


def seed_rejected_authorship(publication_id: int, *, person_id: int) -> None:
    """Rejet de la paire publication ↔ personne."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO rejected_authorships (publication_id, person_id) VALUES (%s, %s)",
            (publication_id, person_id),
        )


def seed_publication(
    title: str = "T",
    *,
    year: int = 2024,
    normalize_title: bool = True,
    doc_type: str | None = "other",
    oa_status: str | None = "unknown",
    journal_id: int | None = None,
    monograph_id: int | None = None,
    in_perimeter: bool = False,
) -> int:
    """Publication de titre normalisé `lower(title)`, NULL si `normalize_title` est faux. Les valeurs par défaut sont celles du schéma ; `None` écrit NULL."""
    return _insert(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, "
        "journal_id, monograph_id, in_perimeter) "
        "VALUES (%s, lower(%s), %s, CAST(%s AS doc_type), CAST(%s AS oa_type), %s, %s, %s) "
        "RETURNING id",
        (
            title,
            title if normalize_title else None,
            year,
            doc_type,
            oa_status,
            journal_id,
            monograph_id,
            in_perimeter,
        ),
    )


def seed_authorship(
    publication_id: int,
    *,
    person_id: int | None = None,
    in_perimeter: bool = False,
    roles: list[str] | None = None,
) -> int:
    """Authorship de `publication_id`. Les valeurs par défaut sont celles du schéma."""
    return _insert(
        "INSERT INTO authorships (publication_id, person_id, in_perimeter, roles) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (publication_id, person_id, in_perimeter, roles),
    )


def seed_in_perimeter_authorships(journal_id: int) -> None:
    """Pose une authorship du périmètre (personne non rejetée) sur chaque publication de la revue, puis matérialise comme le pipeline `publications.in_perimeter` et les `pub_count` de la revue et de son éditeur."""
    with owner_pool() as cur:
        cur.execute("SELECT id FROM publications WHERE journal_id = %s", (journal_id,))
        pub_ids = [r["id"] for r in cur.fetchall()]
        for pid in pub_ids:
            person_id = seed_person(
                uniq("Author"),
                "Jane",
                normalizer="normalize_name_form",
                first_name_normalized="jane",
            )
            seed_authorship(pid, person_id=person_id, in_perimeter=True, roles=["author"])
        cur.execute(
            "UPDATE publications p SET in_perimeter = EXISTS ("
            "SELECT 1 FROM authorships a JOIN persons pe "
            "ON pe.id = a.person_id AND pe.exclusion IS NULL "
            "WHERE a.publication_id = p.id AND a.in_perimeter = TRUE) "
            "WHERE p.journal_id = %s",
            (journal_id,),
        )
        cur.execute(
            "UPDATE journals j SET pub_count = COALESCE((SELECT COUNT(*) "
            "FROM publications p WHERE p.journal_id = j.id AND p.in_perimeter "
            "AND p.doc_type NOT IN ('memoir', 'peer_review')), 0) WHERE j.id = %s",
            (journal_id,),
        )
        cur.execute(
            "UPDATE publishers pub SET pub_count = COALESCE((SELECT SUM(j.pub_count) "
            "FROM journals j WHERE j.publisher_id = pub.id), 0) "
            "WHERE pub.id = (SELECT publisher_id FROM journals WHERE id = %s)",
            (journal_id,),
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
