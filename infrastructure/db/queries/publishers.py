"""Query services pour les éditeurs (table `publishers`)."""

from typing import Any

_SORT_MAP = {
    "name": "p.name ASC",
    "-name": "p.name DESC",
    "journals": "journal_count ASC, p.name ASC",
    "-journals": "journal_count DESC, p.name ASC",
    "pubs": "pub_count ASC, p.name ASC",
    "-pubs": "pub_count DESC, p.name ASC",
}


async def list_publishers_async(
    cur: Any,
    *,
    search: str | None,
    sort: str,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Liste paginée des éditeurs avec comptage revues + publications.

    `search` est ignoré si < 2 caractères. `sort` retombe sur `name` si
    inconnu. Retourne `{total, page, pages, publishers}`.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if search and len(search) >= 2:
        conditions.append("p.name_normalized LIKE '%%' || %s || '%%'")
        params.append(search.lower())
    where = " AND ".join(conditions) if conditions else "TRUE"

    await cur.execute(f"SELECT COUNT(*) FROM publishers p WHERE {where}", params)
    total = (await cur.fetchone())["count"]

    order = _SORT_MAP.get(sort, _SORT_MAP["name"])
    offset = (page - 1) * per_page
    await cur.execute(
        f"""
        SELECT p.id, p.name, p.openalex_id, p.country,
               p.doi_prefix, p.is_predatory,
               (SELECT COUNT(*) FROM journals j WHERE j.publisher_id = p.id) AS journal_count,
               (SELECT COUNT(*) FROM publications pub
                JOIN journals j2 ON j2.id = pub.journal_id
                WHERE j2.publisher_id = p.id) AS pub_count
        FROM publishers p
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
        "publishers": await cur.fetchall(),
    }


async def get_publisher_async(cur: Any, publisher_id: int) -> dict[str, Any] | None:
    """Éditeur par id (nom uniquement). None si absent."""
    await cur.execute("SELECT id, name FROM publishers WHERE id = %s", (publisher_id,))
    return await cur.fetchone()


async def existing_publisher_ids(cur: Any, publisher_ids: tuple[int, ...]) -> set[int]:
    """IDs d'éditeurs existant en base parmi ceux passés."""
    if not publisher_ids:
        return set()
    placeholders = ", ".join(["%s"] * len(publisher_ids))
    await cur.execute(
        f"SELECT id FROM publishers WHERE id IN ({placeholders})",
        publisher_ids,
    )
    return {row["id"] for row in await cur.fetchall()}
