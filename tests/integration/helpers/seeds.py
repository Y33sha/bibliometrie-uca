"""Semis de données pour les tests d'API, sur le pool propriétaire (`owner_pool`).

Chaque fonction insère une ligne, valeurs par défaut uniques quand la table l'exige, et renvoie son `id`.
"""

import json
import uuid

from domain.normalize import normalize_text
from tests.integration.helpers.contributions import upsert_contributor_information_on_cursor
from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.persons import NORMALIZERS
from tests.integration.helpers.rows import perimeter_evidence


def uniq(prefix: str, sep: str = "_") -> str:
    """`prefix` suivi d'un suffixe aléatoire de 8 caractères hexadécimaux."""
    return f"{prefix}{sep}{uuid.uuid4().hex[:8]}"


def _insert(sql: str, params: tuple) -> int:
    with owner_pool() as cur:
        cur.execute(sql, params)
        return cur.fetchone()["id"]


def seed_address(
    raw_text: str, *, countries: list[str] | None = None, publication_count: int = 1
) -> int:
    return _insert(
        "INSERT INTO addresses (raw_text, normalized_text, countries, publication_count) "
        "VALUES (%s, lower(%s), %s, %s) RETURNING id",
        (raw_text, raw_text, countries, publication_count),
    )


def seed_structure(
    code: str | None = None,
    type_: str = "labo",
    *,
    name: str | None = None,
    hal_collection: str | None = None,
    reuse: bool = False,
) -> int:
    """Structure de code unique par défaut ; le nom vaut le code par défaut. `reuse` renvoie la structure de même code si elle existe."""
    code = code or uniq("STR")
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type, hal_collection) "
            "VALUES (%s, %s, CAST(%s AS structure_type), %s)"
            + (" ON CONFLICT (code) DO NOTHING" if reuse else "")
            + " RETURNING id",
            (code, name or code, type_, hal_collection),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT id FROM structures WHERE code = %s", (code,))
            row = cur.fetchone()
        return row["id"]


def seed_structure_name_form(structure_id: int, form_text: str | None = None) -> int:
    """Forme de nom de structure ; une forme de 6 caractères au plus est en mots entiers, comme l'exige la table."""
    form_text = form_text or uniq("form")
    return _insert(
        "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
        "VALUES (%s, %s, char_length(%s) <= 6) RETURNING id",
        (structure_id, form_text, form_text),
    )


def seed_perimeter(
    code: str | None = None,
    root_structure_ids: list[int] | None = None,
    name: str | None = None,
    *,
    replace: bool = False,
) -> int:
    """Périmètre de code unique par défaut. `replace` remplace les racines d'un périmètre de même code."""
    code = code or uniq("perim")
    conflict = (
        " ON CONFLICT (code) DO UPDATE SET root_structure_ids = EXCLUDED.root_structure_ids"
        if replace
        else ""
    )
    return _insert(
        "INSERT INTO perimeters (code, name, root_structure_ids) VALUES (%s, %s, %s)"
        + conflict
        + " RETURNING id",
        (code, name or code, root_structure_ids or []),
    )


def seed_add_to_perimeter(structure_id: int, *, code: str, name: str) -> int:
    """Rattache `structure_id` au périmètre `code`, créé sous le nom `name` s'il est absent, et renvoie l'`id` du périmètre."""
    perimeter_id = _insert(
        "INSERT INTO perimeters (code, name) VALUES (%s, %s) "
        "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id",
        (code, name),
    )
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO perimeter_structures (perimeter_id, structure_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (perimeter_id, structure_id),
        )
    return perimeter_id


def seed_tutelle(parent_id: int, *, child_id: int) -> int:
    """Tutelle de `parent_id` sur `child_id`."""
    return _insert(
        "INSERT INTO structure_parents (parent_id, child_id) VALUES (%s, %s) RETURNING id",
        (parent_id, child_id),
    )


def seed_address_structure(
    address_id: int,
    *,
    structure_id: int,
    matched_form_id: int | None = None,
    is_confirmed: bool | None = None,
) -> int:
    """Lien de l'adresse `address_id` à la structure `structure_id`."""
    return _insert(
        "INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (address_id, structure_id, matched_form_id, is_confirmed),
    )


def seed_country(code: str, name: str) -> None:
    """Pays `code`, s'il est absent du référentiel."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (code, name),
        )


def seed_config(key: str, value: object) -> None:
    """Paramètre `key` à `value`, sérialisé en jsonb, en remplaçant une valeur existante."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO config (key, value) VALUES (%s, CAST(%s AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, json.dumps(value)),
        )


def seed_publisher(name: str | None = None, *, name_normalized: str | None = None) -> int:
    """Éditeur de nom unique par défaut, normalisé par `normalize_text` sauf `name_normalized`."""
    name = name or uniq("Publisher")
    return _insert(
        "INSERT INTO publishers (name, name_normalized) VALUES (%s, %s) RETURNING id",
        (name, normalize_text(name) if name_normalized is None else name_normalized),
    )


def seed_serial(
    title: str | None = None,
    *,
    title_normalized: str | None = None,
    publisher_id: int | None = None,
    serial_type: str = "unknown",
) -> int:
    """Revue de titre unique par défaut, normalisé par `normalize_text` sauf `title_normalized`. Le type par défaut est celui du schéma."""
    title = title or uniq("Journal")
    return _insert(
        "INSERT INTO serials (title, title_normalized, publisher_id, serial_type) "
        "VALUES (%s, %s, %s, CAST(%s AS serial_type)) RETURNING id",
        (
            title,
            normalize_text(title) if title_normalized is None else title_normalized,
            publisher_id,
            serial_type,
        ),
    )


def seed_serial_issn(
    serial_id: int,
    *,
    issn: str,
    support: str | None = None,
    linking: bool = False,
    status: str = "active",
) -> int:
    """ISSN de la revue `serial_id`. Les valeurs par défaut sont celles du schéma."""
    return _insert(
        "INSERT INTO serial_issns (issn, serial_id, support, linking, status) "
        "VALUES (%s, %s, CAST(%s AS issn_support), %s, CAST(%s AS issn_status)) RETURNING id",
        (issn, serial_id, support, linking, status),
    )


def seed_monograph(title: str, *, proceedings: bool = False, isbn: str | None = None) -> int:
    """Monographie de titre normalisé par `normalize_text`."""
    return _insert(
        "INSERT INTO monographs (title, title_normalized, proceedings, isbn)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (title, normalize_text(title), proceedings, isbn),
    )


def seed_person(
    last: str = "TEST",
    first: str = "J",
    *,
    normalizer: str = "lower",
    first_name_normalized: str | None = None,
) -> int:
    """Personne aux nom et prénom normalisés par `normalizer` (`lower` ou `normalize_text`). `first_name_normalized` impose le prénom normalisé."""
    normalize = NORMALIZERS[normalizer]
    return _insert(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (
            last,
            first,
            normalize(last),
            normalize(first) if first_name_normalized is None else first_name_normalized,
        ),
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


def seed_rejected_contribution(publication_id: int, *, person_id: int) -> None:
    """Rejet de la paire publication ↔ personne, comme l'administration : un rejet par enregistrement source de la publication. Une publication sans enregistrement source en reçoit une."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO source_records (source, source_id, title, publication_id) "
            "SELECT 'hal', 'rejet-' || %s, 'X', %s "
            "WHERE NOT EXISTS (SELECT 1 FROM source_records WHERE publication_id = %s)",
            (publication_id, publication_id, publication_id),
        )
        cur.execute(
            "INSERT INTO rejected_contributions (source_record_id, person_id) "
            "SELECT id, %s FROM source_records WHERE publication_id = %s",
            (person_id, publication_id),
        )


def seed_publication(
    title: str = "T",
    *,
    year: int = 2024,
    normalize_title: bool = True,
    doc_type: str | None = "other",
    oa_status: str | None = "unknown",
    serial_id: int | None = None,
    monograph_id: int | None = None,
    publisher_id: int | None = None,
    in_perimeter: bool = False,
) -> int:
    """Publication de titre normalisé `lower(title)`, NULL si `normalize_title` est faux. Les valeurs par défaut sont celles du schéma ; `None` écrit NULL."""
    return _insert(
        "INSERT INTO publications (title, title_normalized, publication_year, doc_type, oa_status, "
        "serial_id, monograph_id, publisher_id, perimeter_evidence) "
        "VALUES (%s, lower(%s), %s, CAST(%s AS doc_type), CAST(%s AS oa_type), %s, %s, %s, "
        "CAST(%s AS perimeter_evidence[])) "
        "RETURNING id",
        (
            title,
            title if normalize_title else None,
            year,
            doc_type,
            oa_status,
            serial_id,
            monograph_id,
            publisher_id,
            perimeter_evidence(in_perimeter) or [],
        ),
    )


def seed_contribution(
    publication_id: int,
    *,
    person_id: int,
    in_perimeter: bool = False,
    roles: list[str] | None = None,
) -> int:
    """Contribution de `publication_id` et `person_id` : groupe de contributions sources rattaché à la personne. Renvoie l'`id` du groupe. Les valeurs par défaut sont celles du schéma."""
    return _insert(
        "INSERT INTO contributions "
        "(publication_id, person_id, resolution_mode, perimeter_evidence, roles) "
        "VALUES (%s, %s, 'manual', CAST(%s AS perimeter_evidence[]), %s) RETURNING id",
        (publication_id, person_id, perimeter_evidence(in_perimeter) or [], roles),
    )


def seed_in_perimeter_contributions(serial_id: int) -> None:
    """Pose une contribution du périmètre (personne non rejetée) sur chaque publication de la revue, puis matérialise comme le pipeline `publications.in_perimeter` et les `publication_count` de la revue et de son éditeur."""
    with owner_pool() as cur:
        cur.execute("SELECT id FROM publications WHERE serial_id = %s", (serial_id,))
        publication_ids = [r["id"] for r in cur.fetchall()]
        for pid in publication_ids:
            person_id = seed_person(
                uniq("Author"),
                "Jane",
                normalizer="normalize_text",
                first_name_normalized="jane",
            )
            seed_contribution(pid, person_id=person_id, in_perimeter=True, roles=["author"])
        cur.execute(
            "UPDATE publications p SET perimeter_evidence = coalesce(("
            "SELECT array_agg(DISTINCT e ORDER BY e) FROM contributions a JOIN persons pe "
            "ON pe.id = a.person_id AND pe.exclusion IS NULL "
            "CROSS JOIN LATERAL unnest(a.perimeter_evidence) e "
            "WHERE a.publication_id = p.id), '{}') "
            "WHERE p.serial_id = %s",
            (serial_id,),
        )
        cur.execute(
            "UPDATE serials j SET publication_count = COALESCE((SELECT COUNT(*) "
            "FROM publications p WHERE p.serial_id = j.id AND p.in_perimeter "
            "AND p.doc_type NOT IN ('memoir', 'peer_review')), 0) WHERE j.id = %s",
            (serial_id,),
        )
        cur.execute(
            "UPDATE publishers pub SET publication_count = COALESCE((SELECT SUM(j.publication_count) "
            "FROM serials j WHERE j.publisher_id = pub.id), 0) "
            "WHERE pub.id = (SELECT publisher_id FROM serials WHERE id = %s)",
            (serial_id,),
        )


def seed_source_record(
    source: str = "hal",
    *,
    source_id: str | None = None,
    title: str = "T",
    publication_year: int | None = 2024,
    publication_id: int | None = None,
    serial_id: int | None = None,
    doc_type: str | None = None,
    raw_doc_type: str | None = None,
    doi: str | None = None,
    corrections: dict[str, object] | None = None,
) -> int:
    """Enregistrement source d'identifiant `source_id`, unique par défaut. Une colonne à `None` garde la valeur par défaut du schéma. `raw_doc_type` vaut par défaut `doc_type`."""
    values = {
        "source": source,
        "source_id": source_id or uniq("sid"),
        "title": title,
        "publication_year": publication_year,
        "publication_id": publication_id,
        "serial_id": serial_id,
        "doc_type": doc_type,
        "raw_doc_type": doc_type if raw_doc_type is None else raw_doc_type,
        "doi": doi,
        "corrections": json.dumps(corrections) if corrections is not None else None,
    }
    values = {column: value for column, value in values.items() if value is not None}
    placeholders = ["CAST(%s AS jsonb)" if column == "corrections" else "%s" for column in values]
    return _insert(
        f"INSERT INTO source_records ({', '.join(values)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING id",
        tuple(values.values()),
    )


def seed_source_contribution(
    source: str = "hal",
    source_record_id: int | None = None,
    in_perimeter: bool = True,
    raw_author_name: str = "Test Author",
    author_position: int = 0,
    identifiers: dict[str, object] | None = None,
) -> int:
    """Contribution source de nom brut `raw_author_name` et d'identifiants `identifiers`, sur un enregistrement source semé au besoin."""
    source_record = source_record_id or seed_source_record(source=source)
    with owner_pool() as cur:
        iid = upsert_contributor_information_on_cursor(cur, raw_author_name.lower(), identifiers)
        cur.execute(
            "INSERT INTO source_contributions (source, source_record_id, author_position, "
            "perimeter_evidence, raw_author_name, contributor_information_id) "
            "VALUES (%s, %s, %s, CAST(%s AS perimeter_evidence[]), %s, %s) RETURNING id",
            (
                source,
                source_record,
                author_position,
                perimeter_evidence(in_perimeter) or [],
                raw_author_name,
                iid,
            ),
        )
        return cur.fetchone()["id"]


def seed_group(publication_id: int, source_contributions: list[tuple[int, int]]) -> int:
    """Groupe des contributions sources `(contribution source, enregistrement source)` de la publication `publication_id` ; la première le fonde, les autres le rejoignent par le nom."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO contributions (publication_id) VALUES (%s) RETURNING id",
            (publication_id,),
        )
        contribution_id = cur.fetchone()["id"]
        for rank, (source_contribution, source_record) in enumerate(source_contributions):
            cur.execute(
                "INSERT INTO aligned_source_contributions "
                "(source_contribution_id, contribution_id, source_record_id, method) "
                "VALUES (%s, %s, %s, CAST(%s AS grouping_method))",
                (
                    source_contribution,
                    contribution_id,
                    source_record,
                    "reference" if rank == 0 else "name",
                ),
            )
        return contribution_id


def seed_perimeter_author_group(
    contribution_id: int, *, person_id: int | None = None, mode: str | None = None
) -> None:
    """Fait du groupe `contribution_id` un groupe d'auteur du périmètre (rôle d'auteur, indice `address`), rattaché à la personne `person_id` par le mode de résolution `mode`."""
    with owner_pool() as cur:
        cur.execute(
            "UPDATE contributions SET person_id = %s, "
            "resolution_mode = CAST(%s AS resolution_mode), roles = ARRAY['author'], "
            "perimeter_evidence = ARRAY['address']::perimeter_evidence[] WHERE id = %s",
            (person_id, mode, contribution_id),
        )


def publication_perimeter_evidence(publication_id: int) -> list[str]:
    """Indices d'appartenance au périmètre de la publication `publication_id`."""
    with owner_pool() as cur:
        cur.execute(
            "SELECT perimeter_evidence::text[] AS evidence FROM publications WHERE id = %s",
            (publication_id,),
        )
        return cur.fetchone()["evidence"]


def group_to_resolve(contribution_id: int) -> bool:
    """Le groupe `contribution_id` est dans la file des groupes dont la personne est à redécider."""
    with owner_pool() as cur:
        cur.execute("SELECT 1 FROM contribution_resolution_queue WHERE id = %s", (contribution_id,))
        return cur.fetchone() is not None


def group_person(contribution_id: int) -> tuple[int | None, str | None]:
    """Personne et mode de résolution du groupe `contribution_id`."""
    with owner_pool() as cur:
        cur.execute(
            "SELECT person_id, resolution_mode::text AS mode FROM contributions WHERE id = %s",
            (contribution_id,),
        )
        row = cur.fetchone()
        return row["person_id"], row["mode"]


def seed_subject(label: str | None = None, *, usage_count: int = 0) -> int:
    """Sujet de libellé unique par défaut. Le compte d'usage par défaut est celui du schéma."""
    label = label or uniq("Subject")
    return _insert(
        "INSERT INTO subjects (label, label_normalized, usage_count) VALUES (%s, %s, %s) RETURNING id",
        (label, normalize_text(label), usage_count),
    )


def seed_publication_subject(publication_id: int, *, subject_id: int, source: str = "hal") -> None:
    """Lien de la publication `publication_id` au sujet `subject_id`."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) "
            "VALUES (%s, %s, CAST(%s AS source_type))",
            (publication_id, subject_id, source),
        )


def seed_doi_prefix(
    prefix: str,
    *,
    ra: str,
    publisher_id: int | None = None,
    crossref_member_id: int | None = None,
) -> None:
    """Préfixe DOI `prefix` de l'agence `ra`."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO doi_prefixes (prefix, ra, publisher_id, crossref_member_id) "
            "VALUES (%s, %s, %s, %s)",
            (prefix, ra, publisher_id, crossref_member_id),
        )


def seed_serial_doi_namespace(namespace: str, *, serial_id: int, dois: int, share: float) -> None:
    """Espace de noms DOI `namespace` appris pour la revue `serial_id`."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO serial_doi_namespaces (namespace, serial_id, dois, share) "
            "VALUES (%s, %s, %s, %s)",
            (namespace, serial_id, dois, share),
        )


def seed_phase_execution(
    run_id: int,
    *,
    phase: str,
    mode: str,
    status: str,
    sources: list[str],
    signals: list[object],
    metrics: dict[str, object],
    details: dict[str, object],
) -> None:
    """Exécution de la phase `phase` du run `run_id`, commencée et finie à l'instant présent."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO pipeline_phase_executions "
            "(run_id, phase, started_at, ended_at, mode, sources, status, signals, metrics, details) "
            "VALUES (%s, %s, now(), now(), %s, %s, %s, "
            "CAST(%s AS jsonb), CAST(%s AS jsonb), CAST(%s AS jsonb))",
            (
                run_id,
                phase,
                mode,
                sources,
                status,
                json.dumps(signals),
                json.dumps(metrics),
                json.dumps(details),
            ),
        )
