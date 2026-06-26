"""person_identifier_keys : matview des couples (personne, identifiant brut)

Substrat diagnostique pour la déduplication des personnes (file « conflits
d'identifiant » du hub admin). Projette `source_authorships.person_identifiers`
au grain « identité » : une ligne par `(person_id, id_type, id_value)` distinct,
hors valeurs neutralisées `_dubious`. Quelques centaines de milliers de lignes au
lieu des ~16-19 M de `source_authorships` : la détection « même identifiant porté
par des personnes distinctes » devient instantanée au lieu de scanner la table de
liaison entière à chaque requête.

Lecture seule, réversible (aucun write-path applicatif) ; rafraîchie par le
pipeline (phase `persons`, `REFRESH MATERIALIZED VIEW CONCURRENTLY`). L'index
unique sur la clé complète autorise le refresh concurrent (sans verrou exclusif).

Revision ID: d5c8b2f1a9e3
Revises: c1a8e4f7b2d9
Create Date: 2026-06-26 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5c8b2f1a9e3"
down_revision: str | Sequence[str] | None = "c1a8e4f7b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW public.person_identifier_keys AS
        SELECT DISTINCT sa.person_id,
                        k AS id_type,
                        sa.person_identifiers->>k AS id_value
        FROM public.source_authorships sa
        CROSS JOIN unnest(ARRAY['orcid', 'idref', 'hal_person_id', 'idhal']) AS k
        WHERE sa.person_id IS NOT NULL
          AND sa.person_identifiers ? k
          AND sa.person_identifiers->>k NOT LIKE '%_dubious'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX idx_person_identifier_keys_uq
            ON public.person_identifier_keys (person_id, id_type, id_value)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_person_identifier_keys_value
            ON public.person_identifier_keys (id_type, id_value)
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS public.person_identifier_keys")
