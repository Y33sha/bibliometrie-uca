# Chantier — Modularité du pipeline

## Contexte

Les phases du pipeline n'ont pas de contrat commun. Chaque `run` de `application/pipeline/<phase>/` a sa propre signature : fabrique de transactions ou connexion, ports ou callables, synchrone ou asynchrone. `interfaces/cli/run_pipeline.py` câble toutes les phases. Une trentaine de fonctions y répètent la même séquence : connexion, circuit breaker, source indisponible, commit. Certaines contiennent de la logique applicative, comme la décision de sauter l'import du DOAJ quand le dernier import est récent.

Plusieurs tables ont plusieurs écrivains : sept phases écrivent `publications`, cinq écrivent `source_authorships`, six endroits écrivent les colonnes de pays.

Certaines phases lisent des données qu'une phase située plus loin dans l'ordre écrit, donc des données du run précédent :

- l'élagage des documents disparus (`normalize`) et le marquage des orphelins (`affiliations`) lisent `source_publications.publication_id` ;
- `resolve_ra` et `fetch_missing` lisent `publications.in_perimeter` et `publication_relations`, à travers la vue `candidate_dois` ;
- `fetch_missing` fait une jointure sur `publications` pour la recherche par identifiant HAL ;
- `publications` lit `source_publications.countries` ;
- la fusion des revues en double (`publishers_journals`) lit `publications.in_perimeter` et met à jour `publications.monograph_id` ;
- `relations` lit ses propres lignes du run précédent avant de purger sa table.

D'autres données sont différées au run suivant sans lecture à rebours. Par exemple, `fetch_missing` n'est pas récursif : un document trouvé par DOI peut fournir un identifiant HAL que seul le run suivant recherche.

Les refontes des phases `countries` et `subjects` relèvent de leurs fiches respectives. Elles s'appuient sur le contrat de phase défini ici.

## Décisions

- **Les données différées au run suivant s'examinent au cas par cas.** Un report peut être un moindre mal accepté, quand la donnée peut attendre le run suivant. Chaque report retenu est justifié. Les autres disparaissent.

## Phasage

### Phase 1 — Contrat de phase et câblage

- [x] Factoriser la séquence connexion, circuit breaker, source indisponible, commit dans un contexte d'exécution unique.
- [x] Définir dans `application/pipeline/` un contrat commun à toutes les phases : `run(contexte) -> PhaseMetrics`. Le contexte regroupe la fabrique de transactions, le logger, le circuit breaker et les options du run.
- [x] Sortir le câblage de chaque phase de `run_pipeline.py`, dans un module par phase. `run_pipeline.py` sélectionne, enchaîne et affiche.
- [x] Déplacer dans `application/` la logique applicative présente dans le câblage. a5924042c, 8238170ae, d6669e4fd, 29f67e81c
- [x] Ranger `fetch_stale` et `fetch_truncated` dans leur propre package, hors de `extract/`. 19c83d094

### Phase 2 — Découpage de publishers_journals

`publishers_journals` enchaîne treize sous-étapes qui touchent tour à tour éditeurs, revues et monographies.

- [x] Réordonner les sous-étapes en quatre groupes : éditeurs, revues, monographies, nettoyage. Une ligne de journal par sous-étape, sous le titre de son groupe.
- [ ] Examiner le découpage en plusieurs phases, une par référentiel.

### Phase 3 — Reports au run suivant

- [ ] Recenser tous les reports : les lectures à rebours ci-dessus, et les données différées sans lecture à rebours (`fetch_missing` non récursif, résolution des personnes par comparaison des sources).
- [ ] Pour chacun, peser le coût du report contre le coût de sa suppression, et trancher.
- [ ] Appliquer les suppressions retenues.

### Phase 4 — Propriété des écritures

- [ ] Recenser les colonnes écrites par plusieurs phases.
- [ ] Donner à chaque colonne une phase propriétaire. Les caches dénormalisés (`publications.countries`, `source_publications.countries`) deviennent des projections recalculées par une seule phase.

### Phase 5 — Connecteurs de source

- [ ] Regrouper par source l'extraction, les re-fetch et la normalisation vers `source_publications`, derrière un registre unique.

### Phase 6 — Documentation

- [ ] Mettre à jour `docs/pipeline/` et `docs/architecture/03-application.md`.

## Questions ouvertes

- Phase 4 : projections en vues matérialisées, ou phase finale de projection ?
- Type des séries et nature des monographies s'appuient l'un sur l'autre. `link_monographs_to_collections` type une série d'après la nature de ses volumes, et ne pose ce type qu'à la création (`set_journal_type_if_unknown`). `type_proceedings_volumes` fait du type de la collection (`monographs.journal_id`) un signal suffisant de volume d'actes. Une série typée recueil d'actes maintient donc ses volumes en volumes d'actes, et le résultat dépend de l'ordre d'arrivée des volumes. Lire le type de collection par les revues des enregistrements, et recalculer le type des séries créées à chaque run ?
- `link_monographs_to_collections` type aussi une revue existante sans ISSN de type `unknown` qu'il retrouve par son titre. Limiter le typage aux séries qu'il crée ?
- Règles de nature d'un volume : un titre d'édition datée de congrès type une revue sans ISSN en recueil d'actes, mais pas un volume. Un volume sans signal propre, dans une série de volumes d'actes, reste un livre. À trancher sur des cas réels.
