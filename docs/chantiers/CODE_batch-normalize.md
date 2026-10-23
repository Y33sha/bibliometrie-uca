# Chantier — Normalisation par lots de documents

## Contexte

La phase `normalize` traite les sources l'une après l'autre, dans l'ordre de `SOURCE_PRIORITY`. Pour chaque source, la boucle de `SourceNormalizer.run` (`pipeline/ingestion/common/normalize.py`) lit le `staging` par sous-lots de 50 lignes. Chaque document est analysé puis écrit sous un SAVEPOINT. Un commit a lieu tous les 100 ou 500 documents selon la source (`DEFAULT_BATCH_SIZE`).

Le writer partagé (`pipeline/ingestion/common/source_contributions.py`) écrit les contributions sources de toutes les sources, theses comprise. Ses requêtes (`SourceContributionStore`, dans `source_contribution_store.py`) traitent déjà plusieurs contributions sources en une requête, mais toujours celles d'un seul document. Le writer fait donc un nombre constant d'allers-retours par document :

- lecture de l'empreinte du bloc auteurs (`fetch_authors_hash`) : un bloc inchangé s'arrête là, sauf avec `--normalize-full` ;
- lecture des contributions sources stockées (`fetch_stored_source_contributions`), relue après insertion pour obtenir les identifiants des contributions sources insérées ;
- écritures : suppressions, mises à jour, insertions de contributions sources, adresses et leurs pays, liens d'adresse, ROR, empreinte du bloc.

Le SAVEPOINT par document isole un document en erreur sans perdre le lot en cours. Regrouper les écritures de plusieurs documents sous un seul SAVEPOINT perd cet isolement.

## Décisions

**Batch optimiste avec repli.** Le writer traite K documents à la fois :

1. analyse des K documents, sans I/O ;
2. lectures et écritures des K documents sous un seul SAVEPOINT, en requêtes ensemblistes ;
3. en cas d'erreur, annulation de ce SAVEPOINT puis rejeu des K documents un par un, un SAVEPOINT par document.

Le rejeu isole le document fautif. Les erreurs sont rares, donc le rejeu l'est aussi.

**Périmètre du lot.** Seules les contributions sources et leurs dépendances passent en lot :

- `fetch_authors_hash` et `fetch_stored_source_contributions` lisent les K `source_record_id` en une requête ;
- `plan_source_contribution_sync` reste par document ;
- suppressions, mises à jour, insertions, adresses, liens d'adresse et ROR deviennent une requête par lot ;
- les identifiants des contributions sources insérées se lisent pour les K documents en une requête.

L'upsert de `source_records` et les `find_or_create` de revues, éditeurs et conteneurs restent par document. Deux documents d'un lot peuvent désigner la même revue.

**Analyse parallèle en second temps.** Les fonctions `build_*_author_records` et l'extraction des métadonnées sont sans I/O. Un pool de processus peut les exécuter pendant qu'un seul processus écrit. Ce parallélisme se décide après la mesure du gain du batch.

## Phasage

### 1. Mesure

- [ ] Profil de `normalize` sur HAL et OpenAlex, avec `--normalize-full` : part de l'analyse, des lectures et des écritures. L'échantillon se rejoue depuis le raw store (`rehydrate_staging_from_raw_store`, puis `run_pipeline --only normalize --sources <source>`).
- [x] HAL, 3 545 enregistrements sources en 450 s : la lecture des contributions sources stockées prend la moitié du temps. Le planificateur sous-estime le nombre d'enregistrements sources distincts de `source_contributions` et choisit un plan parallèle, dont le lancement coûte 55 ms par requête. Une migration fixe l'estimation (`n_distinct`).
- [x] HAL après la migration, 4 435 enregistrements sources en 190 s sous profileur : 43 ms par enregistrement source au lieu de 127. L'attente de PostgreSQL ne fait plus que 49 s. Le reste est du calcul Python, grossi par le profileur. `sanitize_raw_text` y coûtait 19 s : le texte d'une adresse était assaini trois fois. `AddressRecord` l'assainit à la construction, et un texte imprimable sort de `sanitize_raw_text` sans parcours caractère par caractère (1,5 µs au lieu de 16).
- [x] OpenAlex après la migration, 5 099 enregistrements sources en 305 s sous profileur : 60 ms par enregistrement source au lieu de 97. La lecture des contributions sources stockées passe de 59 à 2,9 ms. L'attente de PostgreSQL fait 81 s ; `sanitize_raw_text` en faisait 70, avant ses deux corrections.
- [x] Sans profileur, après les trois corrections : 27 ms par enregistrement source pour HAL (5 089 enregistrements sources en 2 min 18 s) comme pour OpenAlex (5 348 en 2 min 26 s).

### 2. Lectures et écritures des contributions sources par lot

- [ ] `SourceContributionStore` : variantes multi-documents des lectures et écritures.
- [ ] Writer : traitement de K documents, repli document par document sur erreur.
- [ ] Boucle de `SourceNormalizer.run` : accumulation de K documents analysés avant écriture.
- [ ] Tests : résultat identique au traitement par document ; un document en erreur isolé par le repli, les autres écrits.
- [ ] Mesure du gain.

### 3. Analyse parallèle

- [ ] Selon la mesure de la phase 2 : pool de processus pour l'analyse, un seul processus d'écriture.

### 4. Mise à jour de la documentation

- [ ] `docs/` : boucle de `normalize`, batch et repli.

## Questions ouvertes

- Le traitement par lots vaut-il son coût ? Sans profileur, l'attente de PostgreSQL représente environ la moitié des 27 ms par enregistrement source.

- Taille K du lot : compromis entre allers-retours économisés et coût du rejeu.
