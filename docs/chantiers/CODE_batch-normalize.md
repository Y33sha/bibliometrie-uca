# Chantier — Normalisation par lots de documents

## Contexte

La phase `normalize` traite les sources l'une après l'autre, dans l'ordre de `SOURCE_PRIORITY`. Pour chaque source, la boucle de `SourceNormalizer.run` (`pipeline/ingestion/common/normalize.py`) lit le `staging` par sous-lots de 50 lignes. Chaque document est analysé puis écrit sous un SAVEPOINT. Un commit a lieu tous les 100 ou 500 documents selon la source (`DEFAULT_BATCH_SIZE`).

Le writer partagé (`pipeline/ingestion/common/signatures.py`) écrit les signatures de toutes les sources, theses comprise. Ses requêtes (`AuthorshipsBatchQueries`, dans `signature_queries.py`) traitent déjà plusieurs signatures en une requête, mais toujours celles d'un seul document. Le writer fait donc un nombre constant d'allers-retours par document :

- lecture de l'empreinte du bloc auteurs (`fetch_authors_hash`) : un bloc inchangé s'arrête là, sauf avec `--normalize-full` ;
- lecture des signatures stockées (`fetch_stored_source_authorships`), relue après insertion pour obtenir les identifiants des signatures insérées ;
- écritures : suppressions, mises à jour, insertions de signatures, adresses et leurs pays, liens d'adresse, ROR, empreinte du bloc.

Le SAVEPOINT par document isole un document en erreur sans perdre le lot en cours. Regrouper les écritures de plusieurs documents sous un seul SAVEPOINT perd cet isolement.

## Décisions

**Batch optimiste avec repli.** Le writer traite K documents à la fois :

1. analyse des K documents, sans I/O ;
2. lectures et écritures des K documents sous un seul SAVEPOINT, en requêtes ensemblistes ;
3. en cas d'erreur, annulation de ce SAVEPOINT puis rejeu des K documents un par un, un SAVEPOINT par document.

Le rejeu isole le document fautif. Les erreurs sont rares, donc le rejeu l'est aussi.

**Périmètre du lot.** Seules les signatures et leurs dépendances passent en lot :

- `fetch_authors_hash` et `fetch_stored_source_authorships` lisent les K `source_publication_id` en une requête ;
- `plan_signature_sync` reste par document ;
- suppressions, mises à jour, insertions, adresses, liens d'adresse et ROR deviennent une requête par lot ;
- les identifiants des signatures insérées se lisent pour les K documents en une requête.

L'upsert de `source_publications` et les `find_or_create` de revues, éditeurs et conteneurs restent par document. Deux documents d'un lot peuvent désigner la même revue.

**Analyse parallèle en second temps.** Les fonctions `build_*_author_records` et l'extraction des métadonnées sont sans I/O. Un pool de processus peut les exécuter pendant qu'un seul processus écrit. Ce parallélisme se décide après la mesure du gain du batch.

## Phasage

### 1. Mesure

- [ ] Profil de `normalize` sur HAL et OpenAlex, avec `--normalize-full` : part de l'analyse, des lectures et des écritures. L'échantillon se rejoue depuis le raw store (`rehydrate_staging_from_raw_store`, puis `run_pipeline --only normalize --sources <source>`).
- [x] HAL, 3 545 notices en 450 s : la lecture des signatures stockées prend la moitié du temps. Le planificateur sous-estime le nombre de notices distinctes de `source_authorships` et choisit un plan parallèle, dont le lancement coûte 55 ms par requête. Une migration fixe l'estimation (`n_distinct`).
- [x] HAL après la migration, 4 435 notices en 190 s sous profileur : 43 ms par notice au lieu de 127. L'attente de PostgreSQL ne fait plus que 49 s. Le reste est du calcul Python, grossi par le profileur. `sanitize_raw_text` y coûtait 19 s : le texte d'une adresse était assaini trois fois. `AddressRecord` l'assainit à la construction.

### 2. Lectures et écritures des signatures par lot

- [ ] `AuthorshipsBatchQueries` : variantes multi-documents des lectures et écritures.
- [ ] Writer : traitement de K documents, repli document par document sur erreur.
- [ ] Boucle de `SourceNormalizer.run` : accumulation de K documents analysés avant écriture.
- [ ] Tests : résultat identique au traitement par document ; un document en erreur isolé par le repli, les autres écrits.
- [ ] Mesure du gain.

### 3. Analyse parallèle

- [ ] Selon la mesure de la phase 2 : pool de processus pour l'analyse, un seul processus d'écriture.

### 4. Mise à jour de la documentation

- [ ] `docs/` : boucle de `normalize`, batch et repli.

## Questions ouvertes

- Taille K du lot : compromis entre allers-retours économisés et coût du rejeu.
