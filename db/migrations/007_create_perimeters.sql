-- Migration 007 : tables périmètres configurables
-- 2026-04-05

CREATE TABLE IF NOT EXISTS perimeters (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS perimeter_rules (
    id SERIAL PRIMARY KEY,
    perimeter_id INTEGER NOT NULL REFERENCES perimeters(id) ON DELETE CASCADE,
    structure_id INTEGER NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    include_children BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (perimeter_id, structure_id)
);

-- Seed : périmètres UCA restreint et élargi
INSERT INTO perimeters (code, name, description) VALUES
    ('uca', 'UCA restreint', 'UCA + labos en tutelle directe. Détermine is_uca.'),
    ('uca_wide', 'UCA élargi', 'UCA restreint + partenaires (CHU, INP...). Détermine structure_ids.')
ON CONFLICT (code) DO NOTHING;

-- Rules pour le périmètre restreint : UCA with children
INSERT INTO perimeter_rules (perimeter_id, structure_id, include_children)
SELECT p.id, s.id, TRUE
FROM perimeters p, structures s
WHERE p.code = 'uca' AND s.code = 'uca'
ON CONFLICT DO NOTHING;

-- Rules pour le périmètre élargi : UCA + CHU + INP with children
INSERT INTO perimeter_rules (perimeter_id, structure_id, include_children)
SELECT p.id, s.id, TRUE
FROM perimeters p, structures s
WHERE p.code = 'uca_wide' AND s.code IN ('uca', 'chu_clermont', 'inp_clermont')
ON CONFLICT DO NOTHING;
