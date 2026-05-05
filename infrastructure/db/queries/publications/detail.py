"""Liste de toutes les années disponibles + détail d'une publication (§2.12 : async)."""

from typing import Any


async def all_years(cur: Any) -> list[int]:
    """Toutes les années de publication disponibles (hors filtre UCA)."""
    await cur.execute("""
        SELECT DISTINCT pub_year FROM publications
        WHERE pub_year IS NOT NULL
        ORDER BY pub_year DESC
    """)
    return [r["pub_year"] for r in await cur.fetchall()]


async def _fetch_biblio_source_authorships(cur: Any, source: str, pub_id: int) -> list[Any]:
    """Authorships HAL / OpenAlex / WoS / ScanR d'une publi, avec adresses agrégées.

    Quand plusieurs `source_publications` de la même source pointent sur la
    même publi canonique (ex: deux Work IDs OpenAlex pour un même DOI), on
    affiche les auteurs de l'**import le plus récent** (`created_at DESC`).
    Les liens vers les sources, eux, sont multiples côté header — cf
    `PublicationHeader.svelte`.

    `raw_affiliation` concatène les `addresses.raw_text` liées via
    `source_authorship_addresses`. `countries` retombe sur les pays
    extraits des adresses si `sa.countries` est NULL.
    """
    await cur.execute(
        """
        SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
               sa.in_perimeter, sa.structure_ids,
               (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id)
                FROM source_authorship_addresses saa2
                JOIN addresses addr ON addr.id = saa2.address_id
                WHERE saa2.source_authorship_id = sa.id) AS raw_affiliation,
               sa.excluded,
               COALESCE(sa.countries,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE saa.source_authorship_id = sa.id
                      AND addr.countries IS NOT NULL)
               ) AS countries
        FROM source_authorships sa
        WHERE sa.source_publication_id = (
            SELECT id FROM source_publications
            WHERE source = %s AND publication_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        )
        ORDER BY sa.author_position
        """,
        (source, pub_id),
    )
    return await cur.fetchall()


async def get_publication_detail(cur: Any, pub_id: int) -> dict[str, Any] | None:
    """Détail complet d'une publication : métadonnées, sources, authorships.

    Retourne None si la publication n'existe pas (caller = 404).
    """
    await cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doi, p.doc_type::text, p.oa_status::text,
               p.language, p.container_title, p.abstract,
               j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
               j.is_predatory AS journal_predatory, j.apc_amount, j.apc_currency,
               j.oa_model,
               pub.id AS publisher_id, pub.name AS publisher_name,
               pub.is_predatory AS publisher_predatory
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        WHERE p.id = %s
        """,
        (pub_id,),
    )
    pub = await cur.fetchone()
    if not pub:
        return None

    # ORDER BY created_at DESC : une publi canonique peut avoir plusieurs
    # `source_publications` pour une même source (cas typique : deux Work
    # IDs OpenAlex partageant un DOI figshare). Le frontend affiche tous
    # les liens, mais `find(s => s.source === 'X')` retombe sur le plus
    # récent — cohérent avec le filtre dans `_fetch_biblio_source_authorships`.
    await cur.execute(
        """
        SELECT sd.source, sd.source_id, sd.doi, sd.hal_collections, sd.countries
        FROM source_publications sd
        WHERE sd.publication_id = %s
        ORDER BY sd.created_at DESC
        """,
        (pub_id,),
    )
    sources = await cur.fetchall()

    await cur.execute(
        """
        SELECT a.author_position, a.in_perimeter, a.is_corresponding,
               a.structure_ids,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'hal') AS source_hal,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'openalex') AS source_openalex,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'wos') AS source_wos,
               EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'scanr') AS source_scanr,
               pe.id AS person_id, pe.last_name, pe.first_name
        FROM authorships a
        JOIN persons pe ON pe.id = a.person_id
        WHERE a.publication_id = %s AND NOT a.excluded
        ORDER BY a.author_position
        """,
        (pub_id,),
    )
    authorships = await cur.fetchall()

    hal_authorships = await _fetch_biblio_source_authorships(cur, "hal", pub_id)
    oa_authorships = await _fetch_biblio_source_authorships(cur, "openalex", pub_id)
    wos_authorships = await _fetch_biblio_source_authorships(cur, "wos", pub_id)
    scanr_authorships = await _fetch_biblio_source_authorships(cur, "scanr", pub_id)

    # Même règle que `_fetch_biblio_source_authorships` : si plusieurs
    # `source_publications` theses.fr pointent sur la même publi, on
    # affiche les auteurs/jury de la plus récente.
    await cur.execute(
        """
        SELECT sa.id, sa.author_position, sa.raw_author_name AS full_name, sa.person_id,
               sa.roles, sa.in_perimeter
        FROM source_authorships sa
        WHERE sa.source_publication_id = (
            SELECT id FROM source_publications
            WHERE source = 'theses' AND publication_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        )
        ORDER BY sa.author_position NULLS LAST, sa.raw_author_name
        """,
        (pub_id,),
    )
    theses_authorships = await cur.fetchall()

    thesis_meta = None
    if pub["doc_type"] in ("thesis", "ongoing_thesis"):
        await cur.execute(
            """
            SELECT sd.meta AS sd_meta, p.meta AS pub_meta
            FROM publications p
            LEFT JOIN source_publications sd ON sd.publication_id = p.id AND sd.source = 'theses'
            WHERE p.id = %s
            LIMIT 1
            """,
            (pub_id,),
        )
        row = await cur.fetchone()
        if row:
            sd_meta = row["sd_meta"] or {}
            pub_meta = row["pub_meta"] or {}
            thesis_meta = {
                "discipline": sd_meta.get("discipline"),
                "ecoles_doctorales": sd_meta.get("ecoles_doctorales"),
                "partenaires": sd_meta.get("partenaires"),
                "date_soutenance": sd_meta.get("date_soutenance")
                or pub_meta.get("date_soutenance"),
                "date_inscription": sd_meta.get("date_inscription")
                or pub_meta.get("date_inscription"),
            }

    subjects = await get_publication_subjects(cur, pub_id)

    all_struct_ids: set[int] = set()
    for rows in (authorships, hal_authorships, oa_authorships, wos_authorships, scanr_authorships):
        for row in rows:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])

    structures: dict[str, Any] = {}
    if all_struct_ids:
        await cur.execute(
            """
            SELECT id, acronym, name, structure_type AS type FROM structures
            WHERE id = ANY(%s)
            """,
            (list(all_struct_ids),),
        )
        for s in await cur.fetchall():
            structures[str(s["id"])] = {
                "acronym": s["acronym"],
                "name": s["name"],
                "type": s["type"],
            }

    return {
        "publication": dict(pub),
        "sources": [dict(s) for s in sources],
        "authorships": [dict(a) for a in authorships],
        "hal_authorships": [dict(a) for a in hal_authorships],
        "openalex_authorships": [dict(a) for a in oa_authorships],
        "wos_authorships": [dict(a) for a in wos_authorships],
        "scanr_authorships": [dict(a) for a in scanr_authorships],
        "theses_authorships": [dict(a) for a in theses_authorships],
        "thesis_meta": thesis_meta,
        "structures": structures,
        "subjects": subjects,
    }


async def get_publication_subjects(cur: Any, pub_id: int) -> list[dict[str, Any]]:
    """Sujets attachés à une publication, dédupliqués par `subject_id`.

    Les sources qui ont annoté chaque sujet sont agrégées dans la colonne
    `sources`. Tri : concepts (avec ontologies) avant libres (ontologies
    vides), puis label alphabétique insensible à la casse.
    """
    await cur.execute(
        """
        SELECT s.id, s.label, s.language, s.ontologies,
               array_agg(DISTINCT ps.source::text ORDER BY ps.source::text) AS sources
        FROM publication_subjects ps
        JOIN subjects s ON s.id = ps.subject_id
        WHERE ps.publication_id = %s
        GROUP BY s.id
        ORDER BY (s.ontologies = '{}'::jsonb), lower(s.label)
        """,
        (pub_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
