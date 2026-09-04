"""Ramène les JSON `null` des colonnes JSONB à NULL SQL

Le type JSONB de SQLAlchemy sérialise `None` en JSON `null`. Les deux se relisent en `None` côté Python, mais SQL les distingue, et une colonne qui mélange les deux formes échappe aux contraintes et aux index qui raisonnent sur NULL.

`author_identifying_keys` en portait la conséquence : son unique `(author_name_normalized, person_identifiers)` en `NULLS NOT DISTINCT` rassemble les signatures sans identifiant sur leur seul nom, et le JSON `null` passait à côté. Le même nom existait donc en deux identités, hachées différemment par la colonne générée `key_hash`. Les signatures de la forme JSON `null` rejoignent l'identité NULL de même nom, dont l'identité en double disparaît.

Revision ID: b3c7e94a2f18
Revises: f8a4d1c73e05
Create Date: 2026-09-04 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3c7e94a2f18"
down_revision: str | Sequence[str] | None = "f8a4d1c73e05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Colonnes JSONB sans sémantique attachée à la distinction des deux formes de nul : la mise à
# NULL y suffit. `author_identifying_keys.person_identifiers` en est absente, traitée à part.
_COLONNES = (
    ("source_publications", "meta"),
    ("source_publications", "biblio"),
    ("source_publications", "topics"),
    ("journals", "doaj_payload"),
    ("structures", "api_ids"),
)


def upgrade() -> None:
    # Les signatures rattachées à une identité JSON `null` rejoignent l'identité NULL de même
    # nom. L'unique en garantit au plus une : le rapprochement est déterministe.
    op.execute("""
        UPDATE source_authorships sa
        SET identity_id = jumelle.id
        FROM author_identifying_keys doublon
        JOIN author_identifying_keys jumelle
          ON jumelle.person_identifiers IS NULL
         AND jumelle.author_name_normalized IS NOT DISTINCT FROM doublon.author_name_normalized
        WHERE jsonb_typeof(doublon.person_identifiers) = 'null'
          AND sa.identity_id = doublon.id
    """)
    op.execute("""
        DELETE FROM author_identifying_keys doublon
        WHERE jsonb_typeof(doublon.person_identifiers) = 'null'
          AND EXISTS (
              SELECT 1 FROM author_identifying_keys jumelle
              WHERE jumelle.person_identifiers IS NULL
                AND jumelle.author_name_normalized IS NOT DISTINCT FROM doublon.author_name_normalized
          )
    """)
    # Les identités JSON `null` restantes n'ont pas de jumelle : leur mise à NULL ne heurte pas
    # l'unique, et recalcule leur `key_hash` sur la sentinelle du nul.
    op.execute(
        "UPDATE author_identifying_keys SET person_identifiers = NULL "
        "WHERE jsonb_typeof(person_identifiers) = 'null'"
    )

    for table, colonne in _COLONNES:
        op.execute(
            f"UPDATE {table} SET {colonne} = NULL WHERE jsonb_typeof({colonne}) = 'null'"  # noqa: S608
        )


def downgrade() -> None:
    """Irréversible : rien ne distingue une valeur ramenée à NULL d'une valeur qui l'était."""
    raise NotImplementedError(
        "Les deux formes de nul sont confondues par la montée : la descente ne peut pas les départager."
    )
