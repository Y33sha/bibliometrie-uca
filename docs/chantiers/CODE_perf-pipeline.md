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

### 2. subjects — périmètre + purge amont (fait)

**Audit** : `recompute_usage_counts` et la matview `subject_cooccurrences` comptaient sur **toutes** les publications, dont 58 % hors-périmètre (2,45M liens `publication_subjects`, seulement 42 % in-perimeter). D'où l'écart « 10 occurrences annoncées vs 2 publications affichées ». Comptages déjà par publication (`COUNT(DISTINCT publication_id)`), pas par `source_publication` — le souci était bien le périmètre, pas la granularité.

**Cause racine** : le modèle création⇒fusion promeut une publication par `source_publication` orphelin sans gate ; 116k restent à **zéro authorship** (hors-périmètre, sans auteur en base, inatteignables dans l'UI). Mesure des catégories portant des sujets : in-perimeter 64 074 pubs / hors-périmètre-avec-auteur 11 pubs / orphelines 116 102 pubs.

**Fix retenu** : purge des publications zéro authorship en **fin de phase authorships** (`purge_orphan_publications`), pas de filtre dans subjects. `publication_subjects` (FK CASCADE) reste alors scopé périmètre → `usage_count` + matview en héritent. Le résidu hors-périmètre conservé (11 pubs / 146 liens) garde ses sujets sur les fiches → « les vues par personne montrent tout » préservé. Un gate au `create` a été écarté : non équivalent (25 571 sources sans auteur matché contribuent des métadonnées à 17 863 pubs in-perimeter via fusion par identifiant — un gate les perdrait ; la purge a posteriori tourne après toutes les passes de fusion, donc les garde).

- [ ] Purge `purge_orphan_publications` en fin d'authorships : DELETE batché (commit par chunk de 5000 → WAL étalé, progression durable) + `VACUUM ANALYZE` simple (réutilisation de l'espace, pas de FULL). La cascade des 1,4M `publication_subjects` est un coût **unique** (liens legacy) : la purge tournant avant subjects, les orphelines re-promues n'en reçoivent plus jamais
- [ ] Effet : ingest subjects + refresh cooccurrences sur ~64k pubs au lieu de ~180k (−58 %)

**Reste** : l'ingest subjects fait toujours clear+ré-ingestion complète des 64k in-perimeter (pas de watermark sur les `source_publications` modifiées). À mesurer après la purge avant de décider d'un vrai incrémental.

**Tapis roulant (chantier séparé)** : `create_publications` re-promeut les 116k orphelins à chaque run (re-fusion → re-purge). Le `VACUUM` simple évite le bloat, mais la phase publications (~181s) re-crée ces 116k pour rien. Tuer le tapis roulant (gate au create attachant les sources sœurs, ou flag `do_not_promote` avec invalidation) dépasse subjects et touche le cœur création⇒fusion → chantier dédié, à froid.

### 3. publishers_journals — API DOAJ

À investiguer : l'enrichissement DOAJ interroge l'API par revue (779 s, interrompu). Leviers probables : staleness (payload DOAJ déjà stocké), parallélisation.

### 4. cross_imports — parallélisation

Backlog ponctuel. Paralléliser les cross-imports entre eux (comme les extracteurs).

## Questions ouvertes

- oa_status : seuil de staleness (N jours) ; le mode `full` force-t-il tout ?
- subjects : qu'est-ce qui rend le re-traitement complet nécessaire aujourd'hui ?
- publishers_journals : le payload DOAJ est-il déjà stocké (→ staleness possible sans re-fetch) ?
