"""Semis d'adresses et de pays pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection, text

from tests.integration.helpers.rows import insert_row


def insert_address(
    conn: Connection,
    raw_text: str = "X",
    *,
    normalized_text: str | None = None,
    countries: list[str] | None = None,
    suggested_countries: list[str] | None = None,
    pub_count: int | None = None,
) -> int:
    """Insère une adresse et renvoie son `id`. Le texte normalisé vaut par défaut le texte brut en minuscules."""
    return insert_row(
        conn,
        "addresses",
        {
            "raw_text": raw_text,
            "normalized_text": normalized_text if normalized_text is not None else raw_text.lower(),
            "countries": countries,
            "suggested_countries": suggested_countries,
            "pub_count": pub_count,
        },
    )


def ensure_country(conn: Connection, code: str, name: str = "Test") -> None:
    """Insère le pays `code` s'il est absent du référentiel."""
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:code, :name) ON CONFLICT DO NOTHING"),
        {"code": code, "name": name},
    )
