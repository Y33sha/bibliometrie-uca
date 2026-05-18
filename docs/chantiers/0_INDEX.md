# Roadmap des roadmaps

*à compléter*

## DATA — Repenser `source_persons` (2026-04-28)

La table `source_persons` était peuplée pour toutes les sources, y compris celles sans identité auteur stable (OA, WoS, auteurs HAL sans compte) avec des `source_id` synthétiques. Le chantier la restreint aux sources avec identifiant stable (HAL avec`personId`, ScanR et theses.fr avec `idref`) ; les identifiants utiles (orcid, idref, idhal, researcher_id) migrent vers une nouvelle colonne `source_authorships.identifiers` JSONB.
*NB*. Le chantier **DATA_simplify-source-tables** va plus loin dans la simplification du schéma en supprimant `source_persons` et `source_structures`.

## METIER — Exploiter sujets et mots-clés (2026-04-30)
