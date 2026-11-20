# Chantier — Réorganisation du pipeline selon ses dépendances

## Contexte

Le graphe calculé par `pipeline/graph.py` compte une dépendance dès qu'une tâche lit une table écrite avant elle. Un relevé à la main des dépendances réelles, tâche par tâche, montre un ordre d'exécution qui contredit deux dépendances et laisse deux cycles :

- `dois.verify_unpaywall` choisit ses DOI d'après le rattachement des enregistrements sources aux publications, fait plus tard par `publications.reconcile` ;
- `publishing.learn_serial_doi_namespaces` écarte les collections de livres, typées plus tard par `publishing.link_monographs_to_collections` ;
- les neutralisations écrites par `persons.arbitrate_identifiers` sont lues par `affiliations.decide_source_contribution_perimeter` et par `author_grouping.align_source_contributions`, placées avant elle.

Le relevé montre aussi des phases qui réunissent des tâches indépendantes : les référentiels ROR et HAL et les pays dans `affiliations`, Unpaywall dans `dois`.

## Décisions

- Ordre cible des blocs et des phases :
  - **Moissonnage et normalisation** : `harvest`, `harvest_by_person`, `fetch_missing`, `fetch_stale`, `fetch_truncated`, `normalize` ;
  - **Référentiels** : `structure_referentials` (`refresh_ror`, `refresh_hal_structures`), `dois` (`resolve_prefixes`, `resolve_dois`), `publishing` ;
  - **Enregistrements sources** : `identifier_arbitration`, `affiliations`, `countries`, `metadata_correction` ;
  - **Entités** : `publications`, `author_grouping`, `persons` ;
  - **Données dérivées** : `finalize`, `open_access`, `relations`, `subjects`.
- `verify_unpaywall` interroge Unpaywall sur le DOI des publications, après `finalize`. Une tâche nouvelle recalcule ensuite le statut open access des publications au verdict modifié (`oa_inputs`), sans consolidation complète. `consolidate_publications` lit le verdict déjà en base.
- `publishing` se termine par `learn_serial_doi_namespaces`, puis `serial_by_doi`, venue de `metadata_correction`.
- Le vote de l'arbitrage des identifiants se passe de l'alignement. Les doublons d'auteur repérés par l'alignement sont lus par l'arbitrage au run suivant.
- L'option `--no-extras` disparaît : `relations` et `subjects` s'exécutent à chaque run.
- Les runs passés gardent leurs phases d'origine dans `pipeline_phase_executions`. Seule la phase `harvest` y est relue par son nom, pour le mode quotidien, et elle reste inchangée.

## Phasage

### Phase 1 — Statut open access en fin de run

- [x] `verify_unpaywall` choisit ses DOI parmi ceux des publications, hors DOI DataCite.
- [x] Tâche `recompute_oa_status` : statut open access de chaque publication, écrit quand il change. Le recalcul suit le verdict d'Unpaywall, la fin d'un embargo et le modèle open access de la revue. Mesure du 2026-11-20 : 58 s pour 79 210 publications, 9 statuts périmés. `verify_unpaywall` cesse de mettre des publications dans `publications_queue`.
- [x] Phase `open_access`, après `finalize`, avec ses lectures et écritures déclarées, et sa vue dans l'administration du pipeline.
- [x] Tests : verdicts écrits sans mise en file, statut recalculé sans consolidation.

### Phase 2 — Fin de `publishing`

- [x] `learn_serial_doi_namespaces` passe après `type_proceedings_volumes`.
- [x] `serial_by_doi` quitte `metadata_correction` pour la fin de `publishing`, dans l'étape `doi_namespaces`. Son module reste avec les corrections, dont il partage le magasin. La matrice de `metadata_correction` dans l'administration perd sa ligne, la table de `publishing` la gagne.

### Phase 3 — Arbitrage des identifiants

- [x] Phase `identifier_arbitration` : `arbitrate_identifiers` quitte `persons` et passe juste après `normalize`.
- [x] Le bilan de `persons` perd celui de l'arbitrage, repris par la phase nouvelle avec sa vue dans l'administration.

### Phase 4 — Référentiels ROR et HAL, pays

- [x] Phase `structure_referentials` : `refresh_ror` et `refresh_hal_structures` quittent `affiliations`.
- [x] Phase `countries` : les quatre tâches des pays quittent `affiliations`.
- [x] Bilan de chaque phase (`assemble`) et vues de l'administration : l'entonnoir des pays quitte la vue de `affiliations` pour celle de `countries`. La vue `countries` d'une ancienne phase du même nom disparaît.
- [x] Ordre des phases : `normalize`, `structure_referentials`, `dois`, `publishing`, `identifier_arbitration`, `affiliations`, `countries`, `metadata_correction`.

### Phase 5 — Blocs

- [ ] `Block` : blocs « Moissonnage et normalisation », « Référentiels », « Enregistrements sources », « Entités », « Données dérivées ». `normalize` rejoint le premier, `relations` et `subjects` le dernier.
- [ ] Suppression de `--no-extras` et de `Phase.extra`.

### Phase 6 — Documentation

- [ ] Chapitres de `docs/pipeline` et liste des phases de `CLAUDE.md`.

## Questions ouvertes

- Moissonnage par source : chaque source enchaînerait moissonnage, recherches et normalisation sans attendre les autres sources. Le run gagnerait la durée perdue à chaque phase à attendre la source la plus lente. Le journal, l'option `--from` et les métriques sont organisés par phase.
