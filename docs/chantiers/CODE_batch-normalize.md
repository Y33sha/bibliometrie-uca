# Chantier — Normalisation par lots de documents

## Contexte

La phase `normalize` traite les sources l'une après l'autre, dans un ordre de priorité fixe. Pour chaque source, une connexion lit le `staging` par sous-lots de 50 lignes. Chaque document est analysé puis écrit sous un SAVEPOINT. Un commit a lieu tous les 500 documents.

Le writer partagé (`application/pipeline/normalize/_authorships_batch.py`) écrit les signatures d'un document en une requête par opération (`jsonb_to_recordset`, `unnest`). Il fait donc un nombre constant d'allers-retours par document :

- lectures : empreinte du bloc auteurs, signatures stockées ;
- écritures : suppressions, mises à jour, insertions de signatures, adresses, liens d'adresse, ROR.

L'écriture domine le temps de la phase, surtout pour les auteurs avec `--normalize-full`. Dans ce mode, la plupart des signatures ont une empreinte inchangée : le temps passe surtout dans les lectures par document.

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
- `fetch_source_authorship_ids_by_position` rend une correspondance `(source_publication_id, position) → id`.

L'upsert de `source_publications` et les `find_or_create` de revues, éditeurs et conteneurs restent par document. Deux documents d'un lot peuvent désigner la même revue.

**Analyse parallèle en second temps.** Les fonctions `build_*_author_records` et l'extraction des métadonnées sont sans I/O. Un pool de processus peut les exécuter pendant qu'un seul processus écrit. Ce parallélisme se décide après la mesure du gain du batch.

## Phasage

### 1. Mesure

- [ ] Profil de `normalize` sur un échantillon par source, avec et sans `--normalize-full` : part de l'analyse, des lectures et des écritures.

### 2. Lectures et écritures des signatures par lot

- [ ] Port `AuthorshipsBatchQueries` : variantes multi-documents des lectures et écritures.
- [ ] Writer : traitement de K documents, repli document par document sur erreur.
- [ ] Boucle de `normalize/base.py` : accumulation de K documents analysés avant écriture.
- [ ] Tests : résultat identique au traitement par document ; un document en erreur isolé par le repli, les autres écrits.
- [ ] Mesure du gain.

### 3. Analyse parallèle

- [ ] Selon la mesure de la phase 2 : pool de processus pour l'analyse, un seul processus d'écriture.

### 4. Mise à jour de la documentation

- [ ] `docs/` : boucle de `normalize`, batch et repli.

## Questions ouvertes

- Taille K du lot : compromis entre allers-retours économisés et coût du rejeu.
- Theses : son upsert par signature (positions `NULL` des non-auteurs) reste hors du writer partagé.
