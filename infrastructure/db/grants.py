"""Droits des rôles de connexion de l'API et du pipeline, décrits par `grants.sql`."""

from pathlib import Path

from sqlalchemy import Connection, text

GRANTS_FILE = Path(__file__).with_name("grants.sql")

# Rôles que `grants.sql` désigne, créés par `roles.sql`.
GRANTED_ROLES = ("bibliometrie_app", "bibliometrie_pipeline")


def grant_statements() -> list[str]:
    """Ordres de `grants.sql`, commentaires retirés, un par élément."""
    lines = [
        line
        for line in GRANTS_FILE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def apply_grants(conn: Connection) -> bool:
    """Applique `grants.sql` quand les rôles de `GRANTED_ROLES` existent. Rend vrai quand les droits sont appliqués."""
    existing = conn.execute(
        text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:roles)"),
        {"roles": list(GRANTED_ROLES)},
    ).scalar_one()
    if existing < len(GRANTED_ROLES):
        return False
    for statement in grant_statements():
        conn.exec_driver_sql(statement)
    return True
