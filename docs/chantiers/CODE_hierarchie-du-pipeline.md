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
- `countries` rejoint `affiliations` : structures, pays, puis indices de périmètre des contributions sources.
- La consolidation de la publication est seule à calculer les champs de la publication. Les phases `countries` et `oa_status` produisent les faits : pays des adresses, réponses d'Unpaywall. Un changement de pays d'une adresse déclenche la consolidation des publications liées à cette adresse. Un changement de réponse d'Unpaywall déclenche la consolidation des publications du DOI.

## Phasage

### Phase 1 — Arborescence récursive

- [x] Type récursif `Step` dans `pipeline/graph.py`. Le titre d'une étape de premier niveau sert de section au journal.
- [x] Prototype sur `publishing` : préfixes DOI, éditeurs, revues (ISSN, rattachement, qualification, espaces de noms DOI), monographies
- [x] Arborescence affichée par `interfaces/cli/dev/pipeline_tree.py`, avec la phrase de chaque étape et, sur option, ses tables lues et écrites
- [x] `affiliations` : structures (référentiels, adresses, partenaires de thèse), pays, périmètre
- [x] `finalize` : purge, périmètre des publications, vues des structures, nettoyage des référentiels de l'édition, compteurs
- [x] `fetch_missing` : recherche par hal-id, par NNT, par numéro de brevet, par DOI
- [x] `normalize` : normalisation par source, retraits, nettoyage

### Phase 2 — Valeurs de la publication calculées par la seule consolidation

- [x] Pays dans la phase `affiliations`, avant la réconciliation
- [x] Consolidation ciblée des publications, sans réconciliation, par la file `publications_queue` (tâche `publications.consolidate`)
- [x] Étape des pays : un changement de pays d'un enregistrement source met en file sa publication. Le recalcul de l'API consolide aussitôt.
- [x] `oa_status` : un changement de réponse de doi.org ou d'Unpaywall met en file les publications du DOI
- [x] Écriture de `publications.countries` retirée de l'étape des pays
- [x] Écriture de `publications.oa_status` retirée de la phase `oa_status`
- [x] `oa_status` après la correction, sur les DOI candidats des enregistrements sources (règle des ancres, hors DOI qui ont une cible) : +21 % de DOI interrogés
- [ ] Source unique pour « DOI inexistant » : `fetch_missing` et la correction lisent `dois` au lieu d'interroger doi.org et de lire `failed_lookups`

### Phase 3 — Premier niveau

- [ ] Arborescence cible ([annexe](CODE_hierarchie-du-pipeline_arborescence.md)), puis arbitrage de chaque écart avec l'exécution : réviser l'arborescence ou la logique
- [ ] `resolve_ra` dans l'étape des préfixes DOI de `publishing` ; agence du préfixe posée à un seul endroit
- [ ] `fetch_truncated` dans la collecte
- [ ] `finalize` : recalcul des données dérivées
- [x] Relations lues au run suivant par `resolve_ra` et `fetch_missing` : délai accepté

### Phase 4 — Documentation

- [ ] `docs/pipeline/01-vue-d-ensemble.md` : arborescence du pipeline
- [ ] `docs/pipeline/04-affiliations.md` et `docs/pipeline/11-enrichissements.md` : pays dans la phase `affiliations`
- [ ] `docs/pipeline/05-publishing.md` : `merge_duplicate_monographs` absent des tâches, `attach_publishers` et `attach_monographs` absents de la page
- [ ] `docs/pipeline/07-publications.md` : file de consolidation et tâche `consolidate`
- [ ] `docs/pipeline/11-enrichissements.md` et page d'`oa_status` : phase avant `publications`, DOI candidats, mise en file
- [ ] `CLAUDE.md` : liste des phases
