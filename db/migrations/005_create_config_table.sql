-- Migration 005 : table config (clé/valeur JSONB)
-- 2026-04-05

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO config (key, value, description) VALUES
    ('pipeline_years_full', '4', 'Mode full/monthly : extraire depuis (année courante - N)'),
    ('pipeline_years_weekly', '1', 'Mode weekly : extraire depuis (année courante - N)'),
    ('openalex_institution_ids', '["i198244214"]', 'IDs institution OpenAlex (filtre lineage)'),
    ('hal_portal', '"clermont-univ"', 'Portail HAL global'),
    ('hal_collections', '{"ACCEPPT":"ACCePPT","ACTE":"ACTé","AME2P":"AME2P","CELIS":"CELIS","CERDI":"CERDI","CHEC":"CHEC","CHELTER":"CHELTER","CLERMA":"CleRMa","CMH":"CMH","LABCS":"ComSocs","CROC":"CROC","GDEC":"GDEC","GEOLAB":"GEOLAB","GRED":"iGReD","ICC":"ICCF","CERHAC":"IHRIM","IMOST":"IMoST","INSTITUT_PASCAL":"IP","LAMP":"LaMP","LAPSCO":"LAPSCO","LESCORES":"LESCORES","LIMOS":"LIMOS","UMR6620":"LMBP","LMGE":"LMGE","LMV":"LMV","LPC-CLERMONT":"LPCA","LRL":"LRL","M2ISH":"M2iSH","MEDIS":"MEDIS","MSHC":"MSH","ND":"NEURO-DOL","OPGC":"OPGC","PHIER":"PHIER","PIAF":"PIAF","RESSOURCES":"Ressources","TERRITOIRES":"Territoires","UMRF":"UMRF","UNH":"UNH"}', 'Collections HAL par labo (code HAL → label)'),
    ('wos_affiliations', '["Univ Clermont Auvergne","CHU Clermont Ferrand","Clermont Auvergne INP","Sigma Clermont"]', 'Noms Organisation-Enhanced WoS')
ON CONFLICT (key) DO NOTHING;
