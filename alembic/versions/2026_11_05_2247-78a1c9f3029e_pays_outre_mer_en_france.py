"""Pays de l'outre-mer ramenés à la France

Revision ID: 78a1c9f3029e
Revises: 5e2b91c7d4a6
Create Date: 2026-11-05 22:47:20.321363

Les codes pays de l'outre-mer français deviennent `fr` partout : référentiels ROR et HAL, noms de lieux, pays candidats et retenus des adresses, pays des contributions sources, des enregistrements sources et des publications. Les lignes de ces territoires quittent `countries`. Une collaboration avec l'outre-mer compte comme nationale.

La migration est irréversible : le territoire d'origine n'est pas conservé.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "78a1c9f3029e"
down_revision: str | Sequence[str] | None = "5e2b91c7d4a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OVERSEAS = ("bl", "gf", "gp", "mf", "mq", "nc", "pf", "pm", "re", "tf", "wf", "yt")
_IN_LIST = "(" + ", ".join(f"'{code}'" for code in _OVERSEAS) + ")"
_ARRAY = "ARRAY[" + ", ".join(f"'{code}'" for code in _OVERSEAS) + "]"

# Colonnes de pays en tableau, et type de leurs éléments.
_ARRAY_COLUMNS = (
    ("structures.addresses", "char(2)"),
    ("sources.source_contributions", "text"),
    ("sources.source_records", "text"),
    ("publications.publications", "text"),
)


def upgrade() -> None:
    op.execute(
        f"UPDATE ref.ror_organizations SET country_code = 'fr' WHERE country_code IN {_IN_LIST}"
    )
    op.execute(
        f"UPDATE ref.hal_structures SET country_code = 'fr' WHERE country_code IN {_IN_LIST}"
    )
    op.execute(f"UPDATE ref.place_name_forms SET iso_code = 'fr' WHERE iso_code IN {_IN_LIST}")
    op.execute(f"""
        INSERT INTO structures.address_country_candidates (address_id, country_code, method, detected_at)
        SELECT address_id, 'fr', method, min(detected_at)
        FROM structures.address_country_candidates
        WHERE country_code IN {_IN_LIST}
        GROUP BY address_id, method
        ON CONFLICT DO NOTHING
    """)
    op.execute(
        f"DELETE FROM structures.address_country_candidates WHERE country_code IN {_IN_LIST}"
    )
    # Tableaux triés et sans doublon, comme les écrit la phase des pays.
    for table, element_type in _ARRAY_COLUMNS:
        op.execute(f"""
            UPDATE {table}
            SET countries = ARRAY(
                SELECT DISTINCT CASE WHEN c IN {_IN_LIST} THEN 'fr' ELSE c END
                FROM unnest(countries) c
                ORDER BY 1
            )
            WHERE countries && {_ARRAY}::{element_type}[]
        """)
    op.execute(f"DELETE FROM ref.countries WHERE code IN {_IN_LIST}")


def downgrade() -> None:
    pass
