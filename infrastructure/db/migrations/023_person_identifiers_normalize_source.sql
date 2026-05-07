-- Normalise person_identifiers.source : tout ce qui n'est ni 'auto' ni 'manual'
-- devient 'auto'. Vestige d'une asymétrie entre idref (qui portait la source de
-- l'authorship porteuse : 'hal', 'scanr', 'theses', etc.) et orcid/idhal qui
-- atterrissaient avec la source par défaut 'auto'. La distinction n'était de
-- toute façon pas consommée — la source d'un identifiant ne reflète que la
-- première source qui l'a vu, pas l'ensemble des sources qui le confirment.
-- À terme, la priorité Crossref pour les ORCID se gèrera côté cascade de
-- matching personnes (avant les autres voies), pas via ce champ.
UPDATE person_identifiers
SET source = 'auto'
WHERE source IS NOT NULL AND source NOT IN ('auto', 'manual');
