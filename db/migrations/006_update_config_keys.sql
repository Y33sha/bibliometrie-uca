-- Migration 006 : remplacer les clés config par source par des clés par mode
-- 2026-04-05

DELETE FROM config WHERE key IN ('openalex_years', 'hal_years', 'wos_years', 'openalex_institution_id');

INSERT INTO config (key, value, description) VALUES
    ('pipeline_years_full', '4', 'Mode full/monthly : extraire depuis (année courante - N)'),
    ('pipeline_years_weekly', '1', 'Mode weekly : extraire depuis (année courante - N)'),
    ('openalex_institution_ids', '["i198244214"]', 'IDs institution OpenAlex (filtre lineage)'),
    ('hal_portal', '"clermont-univ"', 'Portail HAL global')
ON CONFLICT (key) DO NOTHING;
