-- Migration 008 : paramètres API dans la table config
-- 2026-04-05

INSERT INTO config (key, value, description) VALUES
    ('openalex_email', '"bibliometrie@uca.fr"', 'Email pour le polite pool OpenAlex'),
    ('wos_api_key', '""', 'Clé API Web of Science (Clarivate)')
ON CONFLICT (key) DO NOTHING;
