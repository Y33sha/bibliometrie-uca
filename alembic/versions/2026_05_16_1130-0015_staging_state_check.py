"""staging : CHECK constraint documentant la machine à états (3 états)

Le cycle de vie d'une row `staging` se résume à 3 états codés par 2
booleans + le contenu de `raw_data` :

| État         | processed | not_found | raw_data |
|--------------|-----------|-----------|----------|
| À traiter    | FALSE     | FALSE     | plein    |
| Normalisée   | TRUE      | FALSE     | `{}`     |
| Non trouvée  | TRUE      | TRUE      | `{}`     |

Combinaison interdite : `not_found=TRUE` avec `processed=FALSE`
(rétrograderait silencieusement un row terminal en "à re-traiter").
Le CHECK verrouille uniquement ce cas — le reste (corrélation
raw_data vidé / processed) est documenté dans `docs/donnees.md` mais
pas verrouillé en SQL (laisse de la marge pour les évolutions
type chantier raw_data_store).

Cf. `docs/chantiers/DATA_cycle-vie-staging.md` (Phase 1) pour le
contexte complet et les phases ultérieures (backoff `not_found_at` /
`next_retry`, détection disparitions, re-fetch périodique).

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-16 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE staging ADD CONSTRAINT staging_not_found_implies_processed "
        "CHECK (NOT not_found OR processed)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE staging DROP CONSTRAINT staging_not_found_implies_processed")
