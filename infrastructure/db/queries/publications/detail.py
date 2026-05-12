"""Liste de toutes les années disponibles + détail d'une publication."""

from typing import Any

from sqlalchemy import Connection, text


def all_years(conn: Connection) -> list[int]:
    """Toutes les années de publication disponibles (hors filtre UCA)."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT pub_year FROM publications
            WHERE pub_year IS NOT NULL
            ORDER BY pub_year DESC
        """)
    ).all()
    return [r.pub_year for r in rows]


def _fetch_biblio_source_authorships(
    conn: Connection, source: str, pub_id: int
) -> list[dict[str, Any]]:
    """Authorships HAL / OpenAlex / WoS / ScanR d'une publi, avec adresses agrégées.

    Quand plusieurs `source_publications` de la même source pointent sur la
    même publi canonique (ex: deux Work IDs OpenAlex pour un même DOI), on
    affiche les auteurs de l'**import le plus récent** (`created_at DESC`).
    Les liens vers les sources, eux, sont multiples côté header — cf
    `PublicationHeader.svelte`.

    `raw_affiliation` concatène les `addresses.raw_text` liées via
    `source_authorship_addresses`. `countries` est lu directement depuis
    `sa.countries` (cache dénormalisé recalculé en fin de pipeline et en
    cascade après chaque modification manuelle d'adresse, cf.
    `application.addresses_countries`).
    """
    rows = conn.execute(
        text("""
            SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
                   sa.in_perimeter, sa.structure_ids,
                   (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id)
                    FROM source_authorship_addresses saa2
                    JOIN addresses addr ON addr.id = saa2.address_id
                    WHERE saa2.source_authorship_id = sa.id) AS raw_affiliation,
                   sa.excluded,
                   sa.countries
            FROM source_authorships sa
            WHERE sa.source_publication_id = (
                SELECT id FROM source_publications
                WHERE source = :src AND publication_id = :pid
                ORDER BY created_at DESC
                LIMIT 1
            )
            ORDER BY sa.author_position
        """),
        {"src": source, "pid": pub_id},
    ).all()
    return [dict(r._mapping) for r in rows]


def get_publication_detail(conn: Connection, pub_id: int) -> dict[str, Any] | None:
    """Détail complet d'une publication : métadonnées, sources, authorships.

    Retourne None si la publication n'existe pas (caller = 404).
    """
    pub_row = conn.execute(
        text("""
            SELECT p.id, p.title, p.pub_year, p.doi, p.doc_type::text AS doc_type,
                   p.oa_status::text AS oa_status,
                   p.language, p.container_title, p.abstract,
                   j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
                   j.is_predatory AS journal_predatory, j.apc_amount, j.apc_currency,
                   j.oa_model,
                   pub.id AS publisher_id, pub.name AS publisher_name,
                   pub.is_predatory AS publisher_predatory
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE p.id = :pid
        """),
        {"pid": pub_id},
    ).one_or_none()
    if not pub_row:
        return None
    pub = dict(pub_row._mapping)

    sources_rows = conn.execute(
        text("""
            SELECT sd.source, sd.source_id, sd.doi, sd.hal_collections, sd.countries
            FROM source_publications sd
            WHERE sd.publication_id = :pid
            ORDER BY sd.created_at DESC
        """),
        {"pid": pub_id},
    ).all()
    sources = [dict(r._mapping) for r in sources_rows]

    auth_rows = conn.execute(
        text("""
            SELECT a.author_position, a.in_perimeter, a.is_corresponding,
                   a.structure_ids,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'hal') AS source_hal,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'openalex') AS source_openalex,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'wos') AS source_wos,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'scanr') AS source_scanr,
                   pe.id AS person_id, pe.last_name, pe.first_name
            FROM authorships a
            JOIN persons pe ON pe.id = a.person_id
            WHERE a.publication_id = :pid AND NOT a.excluded
            ORDER BY a.author_position
        """),
        {"pid": pub_id},
    ).all()
    authorships = [dict(r._mapping) for r in auth_rows]

    hal_authorships = _fetch_biblio_source_authorships(conn, "hal", pub_id)
    oa_authorships = _fetch_biblio_source_authorships(conn, "openalex", pub_id)
    wos_authorships = _fetch_biblio_source_authorships(conn, "wos", pub_id)
    scanr_authorships = _fetch_biblio_source_authorships(conn, "scanr", pub_id)

    theses_rows = conn.execute(
        text("""
            SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
                   sa.roles, sa.in_perimeter
            FROM source_authorships sa
            WHERE sa.source_publication_id = (
                SELECT id FROM source_publications
                WHERE source = 'theses' AND publication_id = :pid
                ORDER BY created_at DESC
                LIMIT 1
            )
            ORDER BY sa.author_position NULLS LAST, sa.raw_author_name
        """),
        {"pid": pub_id},
    ).all()
    theses_authorships = [dict(r._mapping) for r in theses_rows]

    thesis_meta = None
    if pub["doc_type"] in ("thesis", "ongoing_thesis"):
        meta_row = conn.execute(
            text("""
                SELECT sd.meta AS sd_meta, p.meta AS pub_meta
                FROM publications p
                LEFT JOIN source_publications sd
                       ON sd.publication_id = p.id AND sd.source = 'theses'
                WHERE p.id = :pid
                LIMIT 1
            """),
            {"pid": pub_id},
        ).one_or_none()
        if meta_row:
            sd_meta = meta_row.sd_meta or {}
            pub_meta = meta_row.pub_meta or {}
            thesis_meta = {
                "discipline": sd_meta.get("discipline"),
                "ecoles_doctorales": sd_meta.get("ecoles_doctorales"),
                "partenaires": sd_meta.get("partenaires"),
                "date_soutenance": sd_meta.get("date_soutenance")
                or pub_meta.get("date_soutenance"),
                "date_inscription": sd_meta.get("date_inscription")
                or pub_meta.get("date_inscription"),
            }

    subjects = get_publication_subjects(conn, pub_id)

    all_struct_ids: set[int] = set()
    for rows in (authorships, hal_authorships, oa_authorships, wos_authorships, scanr_authorships):
        for row in rows:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])

    structures: dict[str, Any] = {}
    if all_struct_ids:
        struct_rows = conn.execute(
            text("""
                SELECT id, acronym, name, structure_type::text AS type FROM structures
                WHERE id = ANY(:ids)
            """),
            {"ids": list(all_struct_ids)},
        ).all()
        for s in struct_rows:
            structures[str(s.id)] = {"acronym": s.acronym, "name": s.name, "type": s.type}

    return {
        "publication": pub,
        "sources": sources,
        "authorships": authorships,
        "hal_authorships": hal_authorships,
        "openalex_authorships": oa_authorships,
        "wos_authorships": wos_authorships,
        "scanr_authorships": scanr_authorships,
        "theses_authorships": theses_authorships,
        "thesis_meta": thesis_meta,
        "structures": structures,
        "subjects": subjects,
    }


def get_publication_subjects(conn: Connection, pub_id: int) -> list[dict[str, Any]]:
    """Sujets attachés à une publication, dédupliqués par `subject_id`.

    Les sources qui ont annoté chaque sujet sont agrégées dans la colonne
    `sources`. Tri : concepts (avec ontologies) avant libres (ontologies
    vides), puis label alphabétique insensible à la casse.
    """
    rows = conn.execute(
        text("""
            SELECT s.id, s.label, s.language, s.ontologies,
                   array_agg(DISTINCT ps.source::text ORDER BY ps.source::text) AS sources
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :pid
            GROUP BY s.id
            ORDER BY (s.ontologies = '{}'::jsonb), lower(s.label)
        """),
        {"pid": pub_id},
    ).all()
    return [dict(r._mapping) for r in rows]
