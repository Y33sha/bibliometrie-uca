"""baseline

Point de départ du chaînage Alembic : le schéma complet de la base, figé
via `pg_dump --schema-only` dans `0001_baseline.sql`, à côté de ce fichier
(tables, vues, enums, fonctions, vues matérialisées, index, contraintes —
exhaustif, là où la MetaData seule ne le serait pas).

Cette migration n'est rejouée que sur une base vierge (tests, nouvel env).
Sur une base déjà au schéma courant (prod, dev), on la marque appliquée via
`alembic stamp 0001`.

Régénération (consolidation des migrations accumulées) : rejouer la chaîne
sur une base vierge ou dumper une base au schéma courant via
`python -m infrastructure.db.dump_schema`, puis dériver le SQL en retirant
le préambule de session pg_dump (`SET statement_timeout`, `search_path`,
directives `\\restrict`/`\\unrestrict`) et la table `alembic_version`, qu'Alembic
gère lui-même. Les vues matérialisées, dumpées `WITH NO DATA`, sont peuplées
par un `REFRESH MATERIALIZED VIEW` en fin de fichier (dans l'ordre d'émission
du dump, qui respecte les dépendances) : non peuplées, elles lèveraient une
erreur à l'interrogation.

Revision ID: 0001
Revises:
Create Date: 2026-05-11 09:38:26.630196
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = Path(__file__).parent / "0001_baseline.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
    # `DROP SCHEMA … CASCADE` supprime aussi la table `alembic_version`,
    # qu'Alembic met à jour juste après ce downgrade. On la recrée pour
    # ne pas laisser la session dans un état où l'INSERT/DELETE final
    # échoue.
    op.execute(
        "CREATE TABLE public.alembic_version ("
        " version_num VARCHAR(32) NOT NULL,"
        " CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    op.execute("INSERT INTO public.alembic_version (version_num) VALUES ('0001')")
