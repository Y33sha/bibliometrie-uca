"""Neutralisation des identifiants d'auteur portée par la signature

Ajoute `source_authorships.neutralized_identifiers` : les identifiants de l'identité que la résolution des personnes ignore pour cette signature, avec leur motif. Les clés d'identité suffixées `_dubious` perdent leur suffixe, et les signatures de ces identités reçoivent le motif `shared` pour ces clés. Une identité qui prend alors la forme d'une identité existante fusionne avec elle. Le retour arrière reconstruit les identités suffixées depuis la colonne.

Revision ID: b4d9e2a7c318
Revises: c5e8a1f2d937
Create Date: 2026-09-14 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4d9e2a7c318"
down_revision: str | Sequence[str] | None = "c5e8a1f2d937"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# L'empreinte reprend l'expression de la colonne générée `author_identifying_keys.key_hash`.
_UPGRADE = r"""
ALTER TABLE public.source_authorships ADD COLUMN neutralized_identifiers jsonb;

COMMENT ON COLUMN public.source_authorships.neutralized_identifiers IS 'Identifiants de l''identité que la résolution des personnes ignore pour cette signature, avec leur motif : {"orcid": "shared"}.';

CREATE TEMP TABLE identites_suffixees ON COMMIT DROP AS
SELECT aik.id,
       aik.author_name_normalized AS nom,
       (SELECT jsonb_object_agg(regexp_replace(e.k, '_dubious$', ''), e.v)
          FROM jsonb_each(aik.person_identifiers) AS e(k, v)) AS nue,
       (SELECT jsonb_object_agg(regexp_replace(k, '_dubious$', ''), 'shared'::text)
          FROM jsonb_object_keys(aik.person_identifiers) AS k
         WHERE k LIKE '%\_dubious') AS carte,
       NULL::integer AS cible
FROM public.author_identifying_keys aik
WHERE EXISTS (
    SELECT 1 FROM jsonb_object_keys(aik.person_identifiers) AS k WHERE k LIKE '%\_dubious'
);

-- Cible d'une identité suffixée dont la forme nue existe déjà en base.
UPDATE identites_suffixees s
SET cible = a.id
FROM public.author_identifying_keys a
WHERE a.key_hash = md5(coalesce(s.nom, E'\x01') || E'\x1f' || coalesce(s.nue::text, E'\x01'));

-- Plusieurs identités suffixées de même forme nue : la plus petite survit.
UPDATE identites_suffixees s
SET cible = g.survivante
FROM (
    SELECT id, min(id) OVER (PARTITION BY nom, nue) AS survivante
    FROM identites_suffixees
    WHERE cible IS NULL
) g
WHERE s.id = g.id AND g.survivante <> g.id;

UPDATE public.source_authorships sa
SET neutralized_identifiers = s.carte
FROM identites_suffixees s
WHERE sa.identity_id = s.id;

UPDATE public.source_authorships sa
SET identity_id = s.cible
FROM identites_suffixees s
WHERE sa.identity_id = s.id AND s.cible IS NOT NULL;

DELETE FROM public.author_identifying_keys a
USING identites_suffixees s
WHERE a.id = s.id AND s.cible IS NOT NULL;

UPDATE public.author_identifying_keys a
SET person_identifiers = s.nue
FROM identites_suffixees s
WHERE a.id = s.id AND s.cible IS NULL;
"""

_DOWNGRADE = r"""
CREATE TEMP TABLE signatures_neutralisees ON COMMIT DROP AS
SELECT sa.id AS signature_id,
       aik.author_name_normalized AS nom,
       (SELECT jsonb_object_agg(
                   CASE WHEN sa.neutralized_identifiers ? e.k THEN e.k || '_dubious' ELSE e.k END,
                   e.v)
          FROM jsonb_each(aik.person_identifiers) AS e(k, v)) AS suffixee
FROM public.source_authorships sa
JOIN public.author_identifying_keys aik ON aik.id = sa.identity_id
WHERE sa.neutralized_identifiers IS NOT NULL;

INSERT INTO public.author_identifying_keys (author_name_normalized, person_identifiers)
SELECT DISTINCT nom, suffixee FROM signatures_neutralisees
ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING;

UPDATE public.source_authorships sa
SET identity_id = a.id
FROM signatures_neutralisees s
JOIN public.author_identifying_keys a
  ON a.key_hash = md5(coalesce(s.nom, E'\x01') || E'\x1f' || coalesce(s.suffixee::text, E'\x01'))
WHERE sa.id = s.signature_id;

DELETE FROM public.author_identifying_keys aik
WHERE NOT EXISTS (SELECT 1 FROM public.source_authorships sa WHERE sa.identity_id = aik.id);

ALTER TABLE public.source_authorships DROP COLUMN neutralized_identifiers;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
