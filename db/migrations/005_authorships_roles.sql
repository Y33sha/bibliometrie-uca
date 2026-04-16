-- Migration 005 : ajouter roles sur authorships (table canonique)
-- Propagé depuis source_authorships.roles par build_authorships.

ALTER TABLE authorships ADD COLUMN IF NOT EXISTS roles text[];

-- Backfill depuis les source_authorships
UPDATE authorships a
SET roles = sub.merged_roles
FROM (
    SELECT sa.authorship_id,
           array_agg(DISTINCT r ORDER BY r) AS merged_roles
    FROM source_authorships sa,
         LATERAL unnest(sa.roles) AS r
    WHERE sa.authorship_id IS NOT NULL
      AND sa.roles IS NOT NULL
    GROUP BY sa.authorship_id
) sub
WHERE a.id = sub.authorship_id
  AND a.roles IS DISTINCT FROM sub.merged_roles;
