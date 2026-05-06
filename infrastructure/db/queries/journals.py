"""Query services pour les revues (table `journals`)."""

from typing import Any

_SORT_MAP = {
    "title": "j.title ASC",
    "-title": "j.title DESC",
    "publisher": "pub_name ASC NULLS LAST, j.title ASC",
    "-publisher": "pub_name DESC NULLS LAST, j.title ASC",
    "pubs": "pub_count ASC, j.title ASC",
    "-pubs": "pub_count DESC, j.title ASC",
}


async def list_journals_async(
    cur: Any,
    *,
    search: str | None,
    publisher_id: int | None,
    sort: str,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Liste paginée des revues avec comptage des publications rattachées.

    `search` est ignoré si < 2 caractères. `sort` retombe sur `title` si
    inconnu. Retourne `{total, page, pages, journals}`.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if search and len(search) >= 2:
        conditions.append("j.title_normalized LIKE '%%' || %s || '%%'")
        params.append(search.lower())
    if publisher_id:
        conditions.append("j.publisher_id = %s")
        params.append(publisher_id)
    where = " AND ".join(conditions) if conditions else "TRUE"

    await cur.execute(f"SELECT COUNT(*) FROM journals j WHERE {where}", params)
    total = (await cur.fetchone())["count"]

    order = _SORT_MAP.get(sort, _SORT_MAP["title"])
    offset = (page - 1) * per_page
    await cur.execute(
        f"""
        SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
               j.publisher_id, p.name AS pub_name,
               j.openalex_id, j.is_in_doaj, j.is_predatory,
               j.apc_amount, j.apc_currency, j.oa_model,
               j.journal_type, j.is_academic, j.doi_prefix, j.notes,
               (SELECT COUNT(*) FROM publications pub
                WHERE pub.journal_id = j.id) AS pub_count
        FROM journals j
        LEFT JOIN publishers p ON p.id = j.publisher_id
        WHERE {where}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    return {
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
        "journals": await cur.fetchall(),
    }


async def get_journal_async(cur: Any, journal_id: int) -> dict[str, Any] | None:
    """Revue par id (titre uniquement). None si absente."""
    await cur.execute("SELECT id, title FROM journals WHERE id = %s", (journal_id,))
    return await cur.fetchone()


async def existing_journal_ids(conn: Any, journal_ids: tuple[int, ...]) -> set[int]:
    """IDs de revues existant en base parmi ceux passés.

    Migrée en SQLAlchemy Core (sous-phase 1.3) : accepte une
    AsyncConnection SA pour rester dans la même transaction que le
    merge qui suit côté router.
    """
    if not journal_ids:
        return set()
    from sqlalchemy import select

    from infrastructure.db.tables import journals

    result = await conn.execute(select(journals.c.id).where(journals.c.id.in_(journal_ids)))
    return {row.id for row in result}
