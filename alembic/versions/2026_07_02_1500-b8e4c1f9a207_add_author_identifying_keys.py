"""author_identifying_keys : table d'identités d'auteur + colonne identity_id (expand)

Première étape de la séparation de `source_authorships` en une table d'identités d'auteur dédupliquées et une table de liaison allégée. Les colonnes d'identification (`author_name_normalized`, `person_identifiers`) dépendent de *qui est l'auteur*, pas de la clé de liaison `(source, source_publication_id, author_position)` ; les répéter sur chaque signature est une dépendance partielle, d'où une répétition d'un facteur d'environ 25.

Cette migration ne fait que l'**expansion** du schéma, sans rien casser : elle crée la table `author_identifying_keys` (clé d'identité `(author_name_normalized, person_identifiers)`, unique `NULLS NOT DISTINCT` pour que les signatures sans identifiant collapsent sur leur seul nom normalisé) et ajoute la colonne `source_authorships.identity_id` **nullable**. Les deux colonnes d'origine restent en place, lues et écrites comme avant. Le backfill dédupliqué des lignes existantes, la bascule des écrivains et des lecteurs, puis le verrouillage (NOT NULL + FK) et la suppression des colonnes, sont des étapes ultérieures.

Revision ID: b8e4c1f9a207
Revises: c7f3a9e21d84
Create Date: 2026-07-02 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e4c1f9a207"
down_revision: str | Sequence[str] | None = "c7f3a9e21d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TABLE public.author_identifying_keys (
    id integer NOT NULL,
    author_name_normalized text,
    person_identifiers jsonb
);

CREATE SEQUENCE public.author_identifying_keys_id_seq AS integer
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.author_identifying_keys_id_seq
    OWNED BY public.author_identifying_keys.id;
ALTER TABLE ONLY public.author_identifying_keys
    ALTER COLUMN id SET DEFAULT nextval('public.author_identifying_keys_id_seq'::regclass);

ALTER TABLE ONLY public.author_identifying_keys
    ADD CONSTRAINT author_identifying_keys_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.author_identifying_keys
    ADD CONSTRAINT author_identifying_keys_key
    UNIQUE NULLS NOT DISTINCT (author_name_normalized, person_identifiers);

ALTER TABLE public.source_authorships ADD COLUMN identity_id integer;
"""

_DOWNGRADE = """
ALTER TABLE public.source_authorships DROP COLUMN IF EXISTS identity_id;
DROP TABLE IF EXISTS public.author_identifying_keys CASCADE;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
