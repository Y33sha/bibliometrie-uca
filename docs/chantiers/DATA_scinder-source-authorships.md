# Chantier — Scinder `source_authorships` (identité ⊥ liaison)

Terminé le 2026-07-03

Décomposer `source_authorships` en deux tables, **à comportement strictement constant** : une table des **identités d'auteur** (forme de nom normalisée + identifiants, dédupliquées) et la table de **liaison** allégée (une FK vers l'identité en remplacement des colonnes déménagées). C'est une pure correction de forme normale : les colonnes d'identification dépendent de *qui est l'auteur*, pas de la clé de liaison `(source, source_publication_id, author_position)` ; les stocker sur la liaison est une dépendance partielle, d'où une répétition d'un facteur ≈ 25. La cible restaure une symétrie déjà à demi-écrite dans le schéma : `addresses` est la table d'identités-source des structures (dédup de chaînes brutes alimentant le matching) ; les personnes n'ont pas d'équivalent, leur identité étant diluée dans la liaison.

Le périmètre se limite au **déplacement des colonnes** : aucun changement de logique de matching, de valeur produite, ni de contrat de lecture (au résultat près, identique). Les gains de performance et les nouveaux diagnostics que la table débloque sont listés en **Suites possibles** et relèvent de chantiers ultérieurs, sur base stable.

## Contexte

### La table et sa redondance

`source_authorships` porte une ligne par authorship source : la relation (`source`, `source_publication_id`, `author_position`, `in_perimeter`, `is_corresponding`, `roles`, `countries`, `authorship_id`, `person_id`) et l'identification de l'auteur (`author_name_normalized`, `raw_author_name`, `person_identifiers`). Les colonnes d'identification sont massivement répétées : une même personne y figure en moyenne une cinquantaine de fois, autant que de signatures qu'elle a déposées.

### Mesures sur une base de travail (≈ 16,75 M lignes ; ≈ 19 M en production)

La table pèse environ 3,3 Go : ≈ 2,58 Go de heap et ≈ 0,74 Go d'index, dont la clé primaire (≈ 0,36 Go) et l'unique `(source_publication_id, author_position)` (≈ 0,36 Go) à eux seuls. Les identités distinctes au sens `(author_name_normalized, person_identifiers)` sont ≈ 645 000, soit un facteur de répétition d'environ 25. Le `person_identifiers` est `NULL` sur ≈ 64 % des lignes.

## Décisions

1. **Deux tables.** `author_identifying_keys` (`id`, `author_name_normalized`, `person_identifiers`) dédupliquée, unique sur `(author_name_normalized, person_identifiers)`. `source_authorships` perd `author_name_normalized` et `person_identifiers`, gagne `identity_id` (FK NOT NULL → `author_identifying_keys`), et garde tout le reste inchangé (`raw_author_name`, `person_id`, `authorship_id`, `in_perimeter`, `author_position`, `is_corresponding`, `roles`, `countries`, `source_structures`).

2. **Clé d'identité = `(author_name_normalized, person_identifiers)`.** Le nom **normalisé** déménage ; le **`raw_author_name` reste sur la liaison** (trace brute par signature). La dédup se fait sur le nom normalisé (déjà le grain du matching) : deux `raw` distincts qui normalisent pareil et portent les mêmes identifiants collapsent en une identité. Le marquage `_dubious` fait partie de la clé (deux valeurs d'identifiant distinctes = deux identités), donc reste invisible au matching comme aujourd'hui.

3. **Relation N:1 : une FK, pas de table de liaison.** Une signature porte exactement une identité — simple FK. Plus simple que le cas des adresses (N:M, via `source_authorship_addresses`), où une signature peut porter plusieurs affiliations.

4. **Pas de `person_id` sur l'identité.** À comportement constant, le matching reste par signature et écrit `person_id` sur la liaison, au même endroit et au même moment. Une colonne `person_id` sur l'identité serait morte : elle n'apparaît qu'avec l'optimisation du matching (Suites possibles), pas ici.

5. **NULL des identifiants et nettoyage des orphelines.** L'unique sur la clé d'identité est posée `NULLS NOT DISTINCT` : les identités sans identifiant (`person_identifiers` à `NULL`, ~64 % des signatures) collapsent bien sur leur seul nom normalisé, sans recourir à un sentinel `'{}'` qu'il faudrait normaliser chez tous les écrivains. Une identité devenue orpheline (plus aucune signature ne la référence, après changement de nom ou d'identifiants d'une signature) est supprimée par un balayage ensembliste `DELETE … WHERE NOT EXISTS (…)` en fin de phase `normalize` — pas de trigger ni de comptage de références. C'est le pendant du nettoyage des `addresses` orphelines, joué systématiquement plutôt qu'à la demande, vu le churn un peu plus élevé des identités.

## Gains et coûts

**Gains**
- **Place** : ≈ 1 Go (≈ 30 %) une fois la table réécrite/repackée — les colonnes creuses (identifiants absents sur 64 % des lignes) cessent d'être répétées. Modéré mais réel sur une table de cette taille.
- **Lisibilité du schéma** : l'identité d'auteur devient une entité nommée, symétrique d'`addresses` ; la liaison n'est plus qu'une liaison.
- **Débloque la suite** : la table dédupliquée est le préalable au matching par identité et aux diagnostics de dédoublonnage (cf. Suites possibles).

**Coûts et risques** (hors charge de travail)
- **Complexité payée maintenant, bénéfice différé.** Le refactor seul ajoute des pièces mobiles (deux tables, FK, contrainte d'unicité, nettoyage des identités orphelines, jointures chez tous les lecteurs) pour un retour immédiat modeste (place + lisibilité de schéma). Le gros du bénéfice (perf du matching, diagnostics) n'arrive qu'aux chantiers suivants. Fait sens comme fondation qu'on **construira**, moins comme fin en soi.
- **Jointure partout sur le read-path.** Chaque lecture de `author_name_normalized` / `person_identifiers` gagne un `JOIN author_identifying_keys` : SQL plus verbeux (contrepoids partiel au gain de lisibilité) et coût de jointure sur les chemins chauds (refresh de matview, audits, fetch du matching). Jointure vers une table de ~645 k lignes : hash join bon marché, mais non nul.
- **Migration lourde et sensible.** Backfill dédupliqué de 17-19 M lignes vers ~645 k identités + pose de la FK, puis `DROP` des deux colonnes (métadonnée immédiate, mais espace récupéré seulement au `VACUUM FULL`/repack). Un bug de dédup ou de gestion du NULL fausserait le grain des identités. Ponctuel, testable sur branche, mais réel.
- **Un invariant de plus à tenir.** Toute écriture de `source_authorships` doit poser `identity_id` ; toute identité sans référent doit être ramassée. Le modèle mono-table actuel a moins de points de défaillance futurs.
- **Une signature n'est plus un enregistrement autonome.** Débogage et SQL ad hoc joignent deux tables au lieu de lire une ligne.

Aucun **coût comportemental** : à migration correcte, les mêmes lignes produisent les mêmes `person_id` et les mêmes lectures (au résultat près, identiques).

## Impact — sites à convertir

Traçage exhaustif des lecteurs et écrivains des deux colonnes. Règle générale : toute **lecture** inline devient un `JOIN author_identifying_keys aik ON aik.id = sa.identity_id` ; toute **écriture** passe par un upsert dédupliqué de l'identité puis pose de `sa.identity_id`. Les usages de la **table** homonyme `person_identifiers` (référentiel des identifiants de personnes) ne sont pas concernés — départagés ligne à ligne lors du traçage.

- **Écrivains — pipeline `normalize`.** Les normalizers par source (`normalize_{hal,openalex,wos,crossref,scanr,datacite,theses}.py`) remplissent le dict d'identifiants et le nom sur leur DTO `AuthorRecord` : inchangés. Les points d'écriture réels sont le writer partagé `application/pipeline/normalize/_authorships_batch.py` et les query services `infrastructure/queries/pipeline/normalize/authorships.py` (`upsert_source_authorships_batch`) et `.../theses.py` (`upsert_theses_source_authorship`) : ils upsertent d'abord l'identité et posent `identity_id`. Les ports `application/ports/pipeline/normalize/authorships.py` et `.../theses.py` suivent.
- **Lecteurs — matching / phase `persons`.** `infrastructure/queries/pipeline/persons_create.py` (projections `fetch_unlinked_authorships`, candidats hors-périmètre, branche identifiant) ; `infrastructure/queries/pipeline/name_forms.py` (`sync_from_raw_forms`) ; `infrastructure/repositories/person_repository/_authorships.py` (`assign_orphan_sa` RETURNING, `get_distinct_name_forms_from_source_authorships`, `null_person_id_for_name_form`) et `_name_forms.py` (`delete_orphan_name_forms_for_person`). Les orchestrateurs Python (`create_persons_from_source_authorships.py`, `assign_orphans.py`, `persons/core.py`) consomment le DTO projeté, pas la colonne : inchangés tant que la projection ramène les mêmes champs.
- **Matview `person_identifier_keys` → supprimée.** Elle matérialisait `(person_id, id_type, id_value)` en lisant `sa.person_identifiers ->> k`. Son unique consommateur (la file « conflits d'identifiant » du hub admin) réévalue désormais cette projection à la volée par un CTE inline, adossé à l'index couvrant `idx_sa_person (person_id, identity_id)` : la matview, son `REFRESH` du pipeline et sa machinerie `REFRESH CONCURRENTLY` disparaissent (cf. Phase 4).
- **API / admin.** `infrastructure/queries/api/persons/admin.py` (`name_form_authorships`, `_REPEATED_OCCURRENCES_SQL` — lit le jsonb entier), `hal_problems.py`, `persons/detail.py`, `persons/list.py` (filtre par forme). `persons/facets.py` et `filters.py` ne touchent que la table homonyme : inchangés.
- **CLI.** Maintenance : `link_source_authorships_by_name.py`, `merge_person_duplicates_by_lab.py`. Oneshots en lecture : `audit_{identifier_linked_person_pairs,identifier_name_corroboration,repeated_person_in_publication,authorships_cross_source,dedup_author_overlap,dedup_overmerge_examples}.py`, `remediate_{rejected_name_forms,identifier_name_incompatible,dubious_agglomerations}.py`. Les oneshots qui **mutaient** le jsonb (`backfill_dubious_{hal,shared}_identifiers.py`) sont supprimés : leur marquage `_dubious` du stock est un backfill daté déjà appliqué, et le flux courant est couvert par `normalize` (qui pose `_dubious` à l'ingestion, désormais partie de la clé d'identité).
- **Frontend.** Aucune lecture directe : il consomme l'API JSON et hérite des changements côté requêtes. Rien à modifier.
- **Tests.** Une vingtaine de fichiers d'intégration à adapter (fixtures `author_identifying_keys` + `identity_id`, jointures) ; les tests unitaires des normalizers restent valides tant que le DTO ne change pas.

Points relevés par le traçage :

- **Aligner le chemin thèses sur la normalisation Python du nom.** Le writer batch calcule `author_name_normalized` en Python (`normalize_name_form`, alias de `normalize_text`) ; l'upsert des thèses le calcule encore en SQL (`normalize_name_form(:raw)`), dans son chemin d'upsert distinct — reliquat de l'unification antérieure qui avait migré HAL mais pas les thèses. Les deux implémentations sont délibérément alignées et gardées par un test, donc les valeurs ne divergent pas ; mais l'upsert d'identité doit calculer la clé de dédup par une seule voie, donc les thèses passent en Python comme les autres sources. La fonction SQL `normalize_name_form` reste — indispensable aux normalisations en SQL (index trigram `subjects`, sync `person_name_forms`, formes de noms journaux/éditeurs).
- **Oneshots `_dubious` supprimés.** Le marquage `_dubious` fait partie de la clé d'identité (Décision 2) : renommer une clé en `<clé>_dubious` changerait l'identité, donc une mutation en place du jsonb n'a plus de sens. Ces backfills de stock datés ont déjà été appliqués, et `normalize` pose `_dubious` à l'ingestion (l'identité `<clé>_dubious` est créée directement) : ils sont retirés plutôt que convertis en re-pointage.
- **Bénéfice de performance collatéral.** La jointure par identifiant, aujourd'hui `sa.person_identifiers ->> 'orcid' = pi.id_value` non indexable sur le jsonb, devient une égalité sur une colonne de `author_identifying_keys`, indexable.

## Phasage

### Phase 1 — Instruction de l'impact

- [x] Tracer exhaustivement les lecteurs/écrivains de `author_name_normalized` et `person_identifiers` — cf. section « Impact — sites à convertir ».

La migration suit le schéma *expand/contract* : on étend le schéma sans rien casser (Phase 2), on bascule écrivains puis lecteurs (Phases 3-4), et on contracte en dernier (Phase 5). Verrouiller ou supprimer les colonnes trop tôt casserait un run `normalize` (écriture) ou un lecteur non basculé.

### Phase 2 — Expand : schéma et backfill

- [x] Table `author_identifying_keys` + unique `NULLS NOT DISTINCT` sur la clé d'identité. (`031bc86c`)
- [x] `source_authorships` : colonne `identity_id` **nullable**, backfill dédupliqué batché des ~19 M lignes vers les identités + pose de `identity_id`. Les deux colonnes d'origine restent en place, lues et écrites comme aujourd'hui. (`031bc86c`, backfill batché `2d0a44ed`)

### Phase 3 — Bascule des écrivains (normalize)

- [x] `normalize` : upsert de l'identité (dédup par clé) + pose de `identity_id` résolu par `key_hash` (colonne générée indexée, NULL-safe ; le rapprochement d'une clé composite nullable n'est indexable ni par `=` ni par `IS NOT DISTINCT FROM`). Normalisation du nom des thèses alignée sur Python. (`8bace239`)
- [x] `normalize` : balayage des identités orphelines en fin de phase (`DELETE FROM author_identifying_keys aik WHERE NOT EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.identity_id = aik.id)`), appuyé sur l'index `idx_sa_identity`. (`f94199e7`)

Les Phases 3 et 4 sont livrées **ensemble**, en un seul déploiement — pas de dual-write. Les deux colonnes d'origine passent directement d'« écrites et lues » à supprimées (Phase 5), sans fenêtre intermédiaire où un écrivain aurait cessé de les remplir pendant qu'un lecteur les lit encore.

### Phase 4 — Bascule des lecteurs

- [x] Matching (fetch de la phase persons) : joindre l'identité, cascade Python inchangée. (`3adc6bc8`)
- [x] Matview `person_identifier_keys` : rediriger sa définition vers l'identité — `source_authorships` (⟶ `person_id`) ⋈ `author_identifying_keys` (⟶ identifiants) — via migration Alembic. (`d7a2f6b3e918`)
- [x] **Matview supprimée au profit d'une lecture à la volée + index couvrant** (mesurée). Le coût de la projection `(person_id, id_type, id_value)` n'est pas l'`unnest` du jsonb (rapide sur les ~271 k identités porteuses d'identifiants) mais la jointure de retour vers `source_authorships` pour récupérer `person_id`, qui vit sur la signature et non sur l'identité : il faut passer sur les ~654 k signatures rattachées. L'index partiel `idx_sa_person` ne portait que `person_id` (non couvrant : accès heap pour lire `identity_id`), et le planificateur lui préférait un parcours complet — ≈ 5,4 s. Étendu à `(person_id, identity_id) WHERE person_id IS NOT NULL`, il autorise un index-only scan (0 heap fetch), faisant tomber la requête réelle de la file « conflits d'identifiant » (self-join complet) à ≈ 0,87 s. Une matview n'avait alors plus de sens : un seul consommateur, sous-la-seconde en live, et matérialiser un demi-calcul entre un index couvrant et une table serait un intermédiaire inutile. La matview `person_identifier_keys`, son `REFRESH` du pipeline et sa machinerie `REFRESH CONCURRENTLY` sont supprimés ; sa projection devient un CTE inline dans le seul consommateur (`_IDENTIFIER_CONFLICT_PAIRS`). File de triage toujours à jour (plus de staleness).
- [x] API / admin / oneshots / `name_forms.py` : jointure à la place de la lecture inline. (`3adc6bc8`)
- [x] Tests de non-régression : mêmes rattachements, mêmes lectures qu'avant. Les fixtures d'intégration sèment l'identité via un helper partagé (`tests/integration/helpers/authorships.py::upsert_identity`) et référencent `identity_id` ; aucun test n'écrit plus `author_name_normalized`/`person_identifiers` sur `source_authorships` (prêt pour le `DROP` de Phase 5).

### Phase 5 — Contract : verrouiller et nettoyer

- [x] `identity_id` : passage NOT NULL + FK vers `author_identifying_keys`. (`f1a7c8b2e4d6`)
- [x] `DROP` de `author_name_normalized` et `person_identifiers` ; espace récupéré au `VACUUM FULL`/repack. (`f1a7c8b2e4d6`)
- [x] Régénérer `infrastructure/db/schema.sql` (`python -m infrastructure.db.dump_schema`).

## Suites possibles (hors périmètre, chantiers ultérieurs)

Ce que la table d'identités débloque, une fois le refactor stable :

- **Matching par identité** : calculer les barreaux sans contexte une fois par identité distincte (~645 k) au lieu d'une fois par signature (17-19 M).
- **Double autorité du `person_id`** : verdict recalculable sur l'identité + autorité sur la liaison (le `cross_source` et le rejet restant contextuels).
- **Diagnostics de dédoublonnage** : divergence entre verdict par identifiant et verdict par nom ; identifiant partagé entre personnes (déjà couvert par `person_identifier_keys`).
- **Résolution nominale ordre-indépendante** : traiter la compatibilité initiale/plein (« J. Martin » / « Jean Martin ») en batch sur l'ensemble des identités, corrigeant une source de doublons sensible à l'ordre d'arrivée.

## Liens

- Tables : `source_authorships`, `source_authorship_addresses`, `authorships`, `persons`, `person_name_forms`, `person_identifiers`.
- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`.
- Analogie structure : phase `affiliations`, `addresses` → `address_structures`.
- Consommateur aval : [DATA_persons-record-linkage](DATA_persons-record-linkage.md) — le grain identité produit ici est le nœud du clustering des personnes.
- Chantier lié : [DATA_personnes-dedoublonnage-assiste](DATA_personnes-dedoublonnage-assiste.md).
