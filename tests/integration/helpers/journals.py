"""Semis des revues, de leurs ISSN et formes de nom, des éditeurs et des monographies, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, text

from tests.integration.helpers.rows import insert_row


def insert_publisher(
    conn: Connection,
    name: str = "X",
    *,
    name_normalized: str | None = None,
    openalex_id: str | None = None,
    publisher_type: str | None = None,
) -> int:
    """Insère un éditeur et renvoie son `id`. Le nom normalisé vaut par défaut le nom en minuscules."""
    return insert_row(
        conn,
        "publishers",
        {
            "name": name,
            "name_normalized": name_normalized if name_normalized is not None else name.lower(),
            "openalex_id": openalex_id,
            "publisher_type": publisher_type,
        },
        {"publisher_type": "publisher_type"},
    )


def insert_journal(
    conn: Connection,
    title: str = "X",
    *,
    title_normalized: str | None = None,
    publisher_id: int | None = None,
    openalex_id: str | None = None,
    journal_type: str | None = None,
    is_in_doaj: bool | None = None,
    oa_model: str | None = None,
    apc_amount: float | None = None,
    apc_currency: str | None = "EUR",
    doaj_imported_at: object = None,
) -> int:
    """Insère une revue et renvoie son `id`. Le titre normalisé vaut par défaut le titre en minuscules. Une colonne facultative laissée à `None` prend la valeur par défaut du schéma. `apc_currency` vaut par défaut celle du schéma ; `None` l'écrit NULL."""
    return insert_row(
        conn,
        "journals",
        {
            "title": title,
            "title_normalized": title_normalized if title_normalized is not None else title.lower(),
            "publisher_id": publisher_id,
            "openalex_id": openalex_id,
            "journal_type": journal_type,
            "is_in_doaj": is_in_doaj,
            "oa_model": oa_model,
            "apc_amount": apc_amount,
            "apc_currency": apc_currency,
            "doaj_imported_at": doaj_imported_at,
        },
        {"journal_type": "journal_type", "oa_model": "oa_model"},
        nullable=("apc_currency",),
    )


def insert_journal_issn(
    conn: Connection,
    journal_id: int | None,
    *,
    issn: str,
    support: str | None = None,
    linking: bool | None = None,
    status: str | None = None,
    sudoc_checked: bool = False,
) -> int:
    """Insère un ISSN de la revue `journal_id` et renvoie son `id`. `sudoc_checked` date la vérification Sudoc de l'instant de la transaction."""
    checked_at = conn.execute(text("SELECT now()")).scalar_one() if sudoc_checked else None
    return insert_row(
        conn,
        "journal_issns",
        {
            "issn": issn,
            "journal_id": journal_id,
            "support": support,
            "linking": linking,
            "status": status,
            "sudoc_checked_at": checked_at,
        },
        {"support": "issn_support", "status": "issn_status"},
    )


def insert_journal_with_issns(
    conn: Connection,
    title: str = "X",
    *,
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    rejected: Iterable[str] = (),
    rejected_status: str = "unverified",
    sudoc_checked: bool = False,
    **columns: Any,
) -> int:
    """Insère une revue avec ses ISSN et renvoie son `id`.

    `issn` est papier, `eissn` électronique, `issnl` marque l'ISSN de liaison ; un `issnl` distinct des deux autres forme son propre ISSN. Chaque valeur de `rejected` forme un ISSN de statut `rejected_status`. `sudoc_checked` s'applique à tous les ISSN. Les autres mots-clés vont à `insert_journal`.
    """
    journal_id = insert_journal(conn, title, **columns)
    rows = []
    if issn:
        rows.append({"issn": issn, "support": "print", "linking": issn == issnl})
    if eissn and eissn != issn:
        rows.append({"issn": eissn, "support": "electronic", "linking": eissn == issnl})
    if issnl and issnl not in (issn, eissn):
        rows.append({"issn": issnl, "linking": True})
    rows += [{"issn": value, "status": rejected_status} for value in rejected]
    for row in rows:
        insert_journal_issn(conn, journal_id, sudoc_checked=sudoc_checked, **row)
    return journal_id


def insert_journal_name_form(
    conn: Connection, journal_id: int, *, form_normalized: str, publisher_id: int | None = None
) -> int:
    """Insère une forme de nom de la revue `journal_id` et renvoie son `id`."""
    return insert_row(
        conn,
        "journal_name_forms",
        {
            "journal_id": journal_id,
            "form_normalized": form_normalized,
            "publisher_id": publisher_id,
        },
    )


def insert_monograph(
    conn: Connection,
    title: str = "X",
    *,
    title_normalized: str | None = None,
    proceedings: bool | None = None,
    publisher_id: int | None = None,
    journal_id: int | None = None,
) -> int:
    """Insère une monographie et renvoie son `id`. Le titre normalisé vaut par défaut le titre en minuscules."""
    return insert_row(
        conn,
        "monographs",
        {
            "title": title,
            "title_normalized": title_normalized if title_normalized is not None else title.lower(),
            "proceedings": proceedings,
            "publisher_id": publisher_id,
            "journal_id": journal_id,
        },
    )


def insert_doi_prefix(
    conn: Connection,
    prefix: str,
    *,
    ra: str,
    publisher_id: int | None = None,
    crossref_member_id: int | None = None,
    checked: bool = False,
) -> None:
    """Insère le préfixe DOI `prefix` de l'agence `ra`. `checked` date la réponse de cette agence de l'instant de la transaction."""
    checked_at = conn.execute(text("SELECT now()")).scalar_one() if checked else None
    insert_row(
        conn,
        "doi_prefixes",
        {
            "prefix": prefix,
            "ra": ra,
            "publisher_id": publisher_id,
            "crossref_member_id": crossref_member_id,
            "crossref_checked_at": checked_at if ra == "Crossref" else None,
            "datacite_checked_at": checked_at if ra == "DataCite" else None,
        },
        returning=False,
    )


def insert_journal_doi_namespace(
    conn: Connection, namespace: str, *, journal_id: int, dois: int, share: float
) -> None:
    """Insère l'espace de noms DOI `namespace` appris pour la revue `journal_id`."""
    insert_row(
        conn,
        "journal_doi_namespaces",
        {"namespace": namespace, "journal_id": journal_id, "dois": dois, "share": share},
        returning=False,
    )


def mark_checked_in_sudoc(conn, journal_id: int) -> None:
    conn.execute(
        text("UPDATE journal_issns SET sudoc_checked_at = now() WHERE journal_id = :id"),
        {"id": journal_id},
    )


def issn_columns(conn, journal_id: int) -> SimpleNamespace:
    """Premier ISSN papier et électronique actifs, ISSN-L, autres valeurs, et date de vérification si tous les ISSN sont vérifiés."""
    rows = conn.execute(
        text(
            "SELECT issn, support::text AS support, linking, status::text AS status, "
            "sudoc_checked_at FROM journal_issns WHERE journal_id = :id ORDER BY id"
        ),
        {"id": journal_id},
    ).all()

    def first(support):
        return next((r.issn for r in rows if r.status == "active" and r.support == support), None)

    issn, eissn = first("print"), first("electronic")
    issnl = next((r.issn for r in rows if r.linking), None)
    checked = [r.sudoc_checked_at for r in rows]
    return SimpleNamespace(
        issn=issn,
        eissn=eissn,
        issnl=issnl,
        rejected_issns=sorted(r.issn for r in rows if r.issn not in (issn, eissn, issnl)),
        sudoc_checked_at=min(checked) if checked and all(checked) else None,
    )
