"""Détail d'une publication."""

from typing import Any

from sqlalchemy import Connection, text

from domain.publications.relations import RelationType, inverse_relation
from domain.source_publications.correction import CONVERGENCE_CASES


def get_publication_relations(conn: Connection, pub_id: int) -> list[dict[str, Any]]:
    """Publications apparentées, des deux sens, vues depuis `pub_id`.

    Les arêtes sortantes (`from_publication_id = pub_id`) gardent leur type ; les entrantes
    (`target_publication_id = pub_id`) sont inversées pour se lire depuis la publication courante.
    La cible porte ses métadonnées si elle est au corpus, sinon seul son DOI est connu. Dédupliqué
    par (type, cible) — une paire déclarée des deux côtés ne s'affiche qu'une fois.
    """
    rows = conn.execute(
        text("""
            WITH rel AS (
                SELECT r.relation_type::text AS rtype, r.target_doi AS other_doi,
                       r.target_publication_id AS other_id, r.source, false AS incoming
                FROM publication_relations r
                WHERE r.from_publication_id = :pid
                UNION ALL
                SELECT r.relation_type::text, src.doi, r.from_publication_id, r.source, true
                FROM publication_relations r
                JOIN publications src ON src.id = r.from_publication_id
                WHERE r.target_publication_id = :pid
            )
            SELECT rel.rtype, rel.other_doi, rel.other_id, rel.source, rel.incoming,
                   p.title AS other_title, p.pub_year AS other_year,
                   p.doc_type::text AS other_doc_type
            FROM rel
            LEFT JOIN publications p ON p.id = rel.other_id
            ORDER BY rel.rtype, p.pub_year DESC NULLS LAST
        """),
        {"pid": pub_id},
    ).all()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        relation_type = r.rtype
        if r.incoming:
            relation_type = inverse_relation(RelationType(relation_type)).value
        # Identité de la cible : son `publication_id` si au corpus, sinon son DOI (cible hors
        # corpus, qui n'a pas de ligne `publications`). Le DOI peut être absent d'une cible au
        # corpus, d'où la bascule sur l'id.
        target_key = f"id:{r.other_id}" if r.other_id is not None else f"doi:{r.other_doi}"
        key = (relation_type, target_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "relation_type": relation_type,
                "doi": r.other_doi,
                "publication_id": r.other_id,
                "title": r.other_title,
                "pub_year": r.other_year,
                "doc_type": r.other_doc_type,
                "source": r.source,
            }
        )
    return out


def _fetch_biblio_source_authorships(
    conn: Connection, source: str, pub_id: int
) -> list[dict[str, Any]]:
    """Authorships HAL / OpenAlex / WoS / ScanR d'une publi, avec adresses agrégées.

    Quand plusieurs `source_publications` de la même source pointent sur la
    même publi canonique (ex: deux Work IDs OpenAlex pour un même DOI), on
    affiche les auteurs de l'**import le plus récent** (`created_at DESC`).
    Les liens vers les sources, eux, sont multiples côté header — cf
    `PublicationHeader.svelte`.

    `raw_affiliation` concatène les `addresses.raw_text` liées via `source_authorship_addresses`. `countries` est dérivé à la volée de ces mêmes adresses (union de leurs pays).
    """
    rows = conn.execute(
        text("""
            SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
                   sa.in_perimeter,
                   (SELECT array_agg(sas.structure_id ORDER BY sas.structure_id)
                    FROM source_authorship_structures sas
                    WHERE sas.source_authorship_id = sa.id) AS structure_ids,
                   (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id)
                    FROM source_authorship_addresses saa2
                    JOIN addresses addr ON addr.id = saa2.address_id
                    WHERE saa2.source_authorship_id = sa.id) AS raw_affiliation,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa3
                    JOIN addresses addr3 ON addr3.id = saa3.address_id
                    CROSS JOIN LATERAL unnest(addr3.countries) AS c
                    WHERE saa3.source_authorship_id = sa.id
                      AND addr3.countries IS NOT NULL) AS countries
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
                   p.language, p.container_title, d.abstract, d.keywords,
                   j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
                   j.apc_amount, j.apc_currency,
                   j.oa_model,
                   pub.id AS publisher_id, pub.name AS publisher_name,
                   dp.ra AS doi_ra
            FROM publications p
            LEFT JOIN publications_detail d ON d.publication_id = p.id
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(p.doi, '/', 1)
            WHERE p.id = :pid
        """),
        {"pid": pub_id},
    ).one_or_none()
    if not pub_row:
        return None
    pub = dict(pub_row._mapping)
    # Mots-clés libres (agrégat des sources) : hors référentiel `subjects`, retournés à part.
    keywords = pub.pop("keywords", None) or []

    sources_rows = conn.execute(
        text("""
            SELECT sd.source, sd.source_id, sd.doi, sd.hal_collections, sd.countries,
                   COALESCE(sd.raw_metadata->'doi'->>'corrected_by' = ANY(:convergence_cases),
                            false) AS is_secondary
            FROM source_publications sd
            WHERE sd.publication_id = :pid
            ORDER BY sd.created_at DESC
        """),
        {"pid": pub_id, "convergence_cases": list(CONVERGENCE_CASES)},
    ).all()
    sources = [dict(r._mapping) for r in sources_rows]

    auth_rows = conn.execute(
        text("""
            SELECT a.author_position, a.in_perimeter, a.is_corresponding,
                   (SELECT array_agg(aus.structure_id ORDER BY aus.structure_id)
                    FROM authorship_structures aus
                    WHERE aus.authorship_id = a.id) AS structure_ids,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'hal') AS source_hal,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'openalex') AS source_openalex,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'wos') AS source_wos,
                   EXISTS (SELECT 1 FROM source_authorships sa
                           WHERE sa.authorship_id = a.id AND sa.source = 'scanr') AS source_scanr,
                   pe.id AS person_id, pe.last_name, pe.first_name,
                   EXISTS (SELECT 1 FROM persons_rh pr WHERE pr.person_id = pe.id) AS has_rh
            FROM authorships a
            JOIN persons pe ON pe.id = a.person_id
            WHERE a.publication_id = :pid
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
    relations = get_publication_relations(conn, pub_id)
    external_identifiers = get_publication_external_identifiers(conn, pub_id)

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
        "keywords": keywords,
        "relations": relations,
        "external_identifiers": external_identifiers,
    }


# Identifiants externes exposés en sidebar, ordre d'affichage. `hal_id` est exclu (déjà couvert
# par le lien source HAL) ; `related_dois` aussi (signal de dédup, pas un identifiant à afficher).
_EXTERNAL_IDENTIFIER_KEYS = (
    ("arxiv", "arxiv_id"),
    ("pmid", "pmid"),
    ("pmcid", "pmcid"),
    ("nnt", "nnt"),
)


def get_publication_external_identifiers(conn: Connection, pub_id: int) -> list[dict[str, Any]]:
    """Identifiants externes (arXiv, PMID, PMCID, NNT) agrégés depuis les `external_ids` des
    `source_publications` de la publication, dédupliqués, dans l'ordre `_EXTERNAL_IDENTIFIER_KEYS`.

    Un NNT déjà porté par une source `theses` est omis : le `source_id` de cette source *est* le
    NNT, et son lien theses.fr couvre déjà l'identifiant (même raison que l'exclusion de `hal_id`,
    couvert par le lien source HAL)."""
    rows = conn.execute(
        text("""
            SELECT sp.source::text, sp.source_id, sp.external_ids FROM source_publications sp
            WHERE sp.publication_id = :pid AND sp.external_ids IS NOT NULL
        """),
        {"pid": pub_id},
    ).all()
    nnt_covered_by_theses = {source_id for source, source_id, _ in rows if source == "theses"}
    out: list[dict[str, Any]] = []
    for id_type, key in _EXTERNAL_IDENTIFIER_KEYS:
        seen: set[str] = set()
        for _source, _source_id, external_ids in rows:
            value = external_ids.get(key)
            if not (isinstance(value, str) and value) or value in seen:
                continue
            if id_type == "nnt" and value in nnt_covered_by_theses:
                continue
            seen.add(value)
            out.append({"type": id_type, "value": value})
    return out


def get_publication_subjects(conn: Connection, pub_id: int) -> list[dict[str, Any]]:
    """Sujets (concepts) attachés à une publication, dédupliqués par `subject_id`.

    Les sources qui ont annoté chaque sujet sont agrégées dans `sources`. Triés par
    label, insensible à la casse.
    """
    rows = conn.execute(
        text("""
            SELECT s.id, s.label, s.language,
                   array_agg(DISTINCT ps.source::text ORDER BY ps.source::text) AS sources
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :pid
            GROUP BY s.id
            ORDER BY lower(s.label)
        """),
        {"pid": pub_id},
    ).all()
    return [dict(r._mapping) for r in rows]
