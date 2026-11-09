# Chantier — Hiérarchie du pipeline

## Contexte

Le pipeline compte 18 phases, en une liste plate de tâches par phase. Certaines phases se décrivent mal en une phrase :

- `publishing` enchaîne 16 tâches sur les préfixes DOI, les éditeurs, les ISSN, les revues et les monographies.
- `finalize` se décrit par une énumération : périmètre, vues, purges, compteurs.
- `resolve_ra` et `fetch_truncated` comptent une seule tâche chacune.

Le cycle de vie d'un référentiel s'étend sur plusieurs phases. Les revues sont créées et qualifiées dans `publishing`, rattachées par DOI dans `metadata_correction`, supprimées et recomptées dans `finalize`. L'agence d'un préfixe DOI est posée par `resolve_ra` et corrigée par `publishing`.

Deux valeurs de la publication sont calculées à deux endroits. La consolidation de la publication, dans `publications`, calcule `publications.countries` et `publications.oa_status`. Les phases `countries` et `oa_status` écrivent aussi ces deux colonnes.

## Décisions

- Chaque élément de l'arborescence a une phrase d'entrées → sorties, écrite dans le code.
- Un seul type récursif décrit l'arborescence : un élément a un nom, sa phrase et ses enfants ; la tâche est la feuille. « Phase » désigne seulement le premier niveau, unité du run dans l'administration et dans `pipeline_phase_executions`.
- L'arborescence donne l'ordre d'exécution. Les tests vérifient sa compatibilité avec les dépendances déclarées par les tâches.
- Le premier niveau se réduit. Les phases d'une seule tâche rejoignent une phase voisine. `finalize` recalcule les données dérivées des entités : périmètre des publications, purges, vues, compteurs.
- La consolidation de la publication est seule à calculer les champs de la publication. Les phases `countries` et `oa_status` produisent les faits : pays des adresses, réponses d'Unpaywall. Un changement de pays d'une adresse déclenche la consolidation des publications liées à cette adresse. Un changement de réponse d'Unpaywall déclenche la consolidation des publications du DOI.

## Phasage

### Phase 1 — Arborescence récursive

- [ ] Type récursif dans `pipeline/graph.py`, à la place de `Task.section`
- [ ] Prototype sur `publishing` : préfixes DOI, éditeurs, ISSN, revues, monographies
- [ ] Arborescence affichée depuis `PHASES`, avec la phrase de chaque élément
- [ ] Autres phases

### Phase 2 — Valeurs de la publication calculées par la seule consolidation

- [ ] Consolidation ciblée des publications, sans réconciliation
- [ ] `countries` : un changement de pays d'une adresse met en attente la consolidation de ses publications
- [ ] `oa_status` : un changement de réponse d'Unpaywall met en attente la consolidation des publications du DOI
- [ ] Écritures de `publications.countries` et `publications.oa_status` retirées des phases `countries` et `oa_status`
- [ ] Place des phases `countries` et `oa_status` dans le run

### Phase 3 — Premier niveau

- [ ] Liste des phases et de leur phrase, soumise avant le code
- [ ] `resolve_ra` dans l'étape des préfixes DOI de `publishing` ; agence du préfixe posée à un seul endroit
- [ ] `fetch_truncated` dans la collecte
- [ ] `finalize` : recalcul des données dérivées
- [ ] Relations lues au run suivant par `resolve_ra` et `fetch_missing`

### Phase 4 — Documentation

- [ ] `docs/pipeline/01-vue-d-ensemble.md` : arborescence du pipeline
- [ ] `docs/pipeline/05-publishing.md` : `merge_duplicate_monographs` absent des tâches, `attach_publishers` et `attach_monographs` absents de la page

## Questions ouvertes

- Consolidation ciblée : file dédiée, ou `source_record_keys_queue`, qui déclenche aussi la réconciliation.
- `relations` : avancer la phase, ou afficher la lecture au run suivant dans l'arborescence.
