# Performance du pipeline (phase par phase)

Commencé le 2026-06-13

## Contexte

Temps observés sur un rapport (daily + full). On attaque les phases par impact décroissant.

**Daily**
- extract : 129 s
- cross_imports : 3598 s — gros lot non traité des jours précédents (one-shot, pas inquiétant en soi ; parallélisable entre cross-imports comme les extracteurs)
- refresh_stale : 1,3 s
- normalize : 383 s (normal vu le gros cross-import)

**Full**
- publishers_journals : 779 s (interrompu en plein milieu de l'API DOAJ — inacceptable)
- affiliations : 149 s
- zenodo_doi : 32 s
- publications : 181 s
- persons : 53 s
- authorships : 46 s
- countries : 50 s
- subjects : 1991 s — inacceptable, à rendre incrémental
- oa_status : 6642 s (interrompu) — >100k interrogations DOI par DOI via Unpaywall, catastrophiquement lent

## Ordre d'attaque (par impact)

1. **oa_status** (6642 s) — le monstre.
2. **subjects** (1991 s) — rendre incrémental.
3. **publishers_journals** (779 s) — l'API DOAJ.
4. **cross_imports** (3598 s, daily) — backlog ponctuel, parallélisation (moindre priorité).

## Phasage

### 1. oa_status — staleness + règles métier (fait, sauf suivi refresh)

État initial : `fetch_publications_with_doi` renvoyait **tous** les ~107k DOI à chaque run via Unpaywall (async `Semaphore(5)`, débit plafonné par la politesse Unpaywall ~10 req/s → cranker la concurrence est inutile/risqué). **Audit** : 97 % des publis ont OpenAlex comme source (dont l'`oa_status` dérive déjà d'Unpaywall), et les corrections sont **déjà appliquées** par les full précédents (0,36 % de changements/run) — mais Unpaywall apporte bien ~2-4 % de corrections réelles vs OpenAlex brut (à ne pas perdre). → pas supprimer, **incrémentaliser** (réduire le volume).

- [x] Colonne `publications.unpaywall_checked_at` (migration `e3f7b2d9c5a8`) + index partiel pour le fetch
- [x] `STABLE_OA_STATUSES` (gold/diamond/hybrid) dans `domain/publications/metadata` (+ forme SQL) — règle métier
- [x] Constantes opérationnelles `MAX_PER_RUN=10000` + `STALENESS_DAYS=30` dans le module de phase (pas domain)
- [x] `fetch_publications_with_doi` : jamais-vérifiés (1× même gold/diamond/hybrid) OU statut changeable périmé ; tri `NULLS FIRST` + cap
- [x] `unpaywall_checked_at = now()` posé à **chaque** vérif (changée, inchangée, non trouvée, diamond préservé)
- [x] `run_oa_status = True` en **daily + weekly** (le cap lisse, le backlog s'écoule run après run)

Effet attendu : ~6642 s (one-shot, backlog écoulé sur ~11 runs à 10k) → quelques dizaines de secondes en régime permanent.

- [x] **Préservation au refresh** : `aggregation.recompute` ne ré-agrège plus `oa_status` quand `unpaywall_checked_at` est posé (Unpaywall fait autorité). Sans ça, un réimport (publi stale → `refresh_from_sources`) écraserait la correction Unpaywall et, la date étant posée, elle ne serait jamais re-vérifiée → perte permanente sur un statut stable-open. L'entité `Publication` porte désormais `unpaywall_checked_at` (chargé par `find_by_id`).

### 2. subjects — incrémental

À investiguer : aujourd'hui re-traite tout (1991 s). Cible : ne traiter que les publications nouvelles/modifiées.

### 3. publishers_journals — API DOAJ

À investiguer : l'enrichissement DOAJ interroge l'API par revue (779 s, interrompu). Leviers probables : staleness (payload DOAJ déjà stocké), parallélisation.

### 4. cross_imports — parallélisation

Backlog ponctuel. Paralléliser les cross-imports entre eux (comme les extracteurs).

## Questions ouvertes

- oa_status : seuil de staleness (N jours) ; le mode `full` force-t-il tout ?
- subjects : qu'est-ce qui rend le re-traitement complet nécessaire aujourd'hui ?
- publishers_journals : le payload DOAJ est-il déjà stocké (→ staleness possible sans re-fetch) ?
