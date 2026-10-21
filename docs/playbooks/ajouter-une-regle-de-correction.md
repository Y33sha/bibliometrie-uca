# Ajouter une règle de correction de métadonnées

Procédure d'écriture, branchement et déploiement d'une règle dans `domain/source_records/metadata_correction/rules.py`.

## Modèle : corrections persistées sur l'enregistrement source

Une correction est une règle déterministe « si tel signal, alors le champ vaut telle valeur ». La phase `metadata_correction` calcule la valeur corrigée de chaque enregistrement source et l'écrit **en place** dans ses colonnes typées. La valeur d'avant correction est conservée dans la colonne JSONB `corrections`. La résolution et l'agrégation lisent ensuite des colonnes corrigées.

- **Source unique** : la règle vit dans [`rules.py`](../../domain/source_records/metadata_correction/rules.py) (fonction pure, zéro I/O), comme entrée du dict `_RULES`. `effective_metadata(facts)` parcourt la cascade et renvoie un `CorrectedFields` (valeur corrigée et règle d'origine par champ).
- **Forme déclarative** : une règle = `{applies_to: {prédicats AND-és}, applies_correction: {champ: valeur cible}}`. `_check_predicate` interprète chaque prédicat. Une règle qui entre dans les prédicats existants est seulement cette entrée.
- **Faits** : `MetadataForCorrection` liste les faits que lisent les règles. Un fait inconnu vaut `None`, et un prédicat sur un fait `None` est faux.
- **Réversibilité** : [`correct_source_record`](../../domain/source_records/metadata_correction/source_record.py) reconstruit les valeurs d'avant correction depuis `corrections`, applique `effective_metadata`, et rend les valeurs corrigées avec la trace `corrections.<champ>` : `{"raw": <valeur d'avant correction>, "corrected_by": <règle>}`.
- **Idempotence** : la correction repart toujours des valeurs d'avant correction, jamais de la valeur déjà corrigée. Un changement de `journal_type` qui déclenche ou désactive une règle est rattrapé au run suivant.
- **Cascade par champ** : `_correct_field(facts, "<champ>")` parcourt `_RULES` dans l'ordre d'insertion et retourne la première règle qui corrige le champ demandé et dont tous les prédicats sont vrais. L'ordre traduit la spécificité du signal : URL, puis `journal_type`, puis titre.
- **Mutation de clé ⇒ résolution** : une correction qui change `doc_type`, `external_ids` ou `doi` pose `keys_dirty` sur l'enregistrement source. `doc_type` entre dans le jeton `metadata_block`, et le `doi` est un jeton. La phase `publications` résout à nouveau ces enregistrements sources au run suivant.
- **Rejeu sur la publication** : après l'arbitrage, `consolidation.py` rejoue les corrections de `doc_type` sur la publication, avec les faits de `MetadataForCorrection.for_publication`. Les règles qui lisent un fait propre à l'enregistrement source (URL, embargo, extras de la source) restent sans effet sur la publication, puisque ce fait y vaut `None`.

## Quand utiliser ce playbook

À chaque ajout d'une règle déterministe qui corrige un champ vers une valeur fixe.

Les incohérences détectables mais sans correction automatique demandent une décision humaine, hors de ce playbook.

## Procédure pas-à-pas

### 1. Caractériser la règle

Avant d'ouvrir un fichier, expliciter :

- **Champ corrigé** : `doc_type` ou `oa_status`.
- **Faits lus** : quels champs de `MetadataForCorrection` ? Un ou plusieurs critères ?
- **Condition** : liste blanche (sur un ensemble fini de valeurs) ou inconditionnelle ? La liste blanche est presque toujours plus défensive : elle épargne les types de référence (`thesis`, `book`…).
- **Origine des faits** :
  - un fait déjà dans `MetadataForCorrection` → rien à câbler ;
  - un fait absent → étendre `MetadataForCorrection` (§ 4).
- **Fait éditable par l'admin ?** Détermine s'il faut un hook (§ 6).
- **Correction qui change le regroupement ?** Une correction de `doc_type` change le jeton `metadata_block` de l'enregistrement source : tester que la résolution utilise la valeur corrigée.

### 2. Audit avant de coder

SQL préliminaire pour mesurer l'ampleur et confirmer que le signal est déterminant. Au minimum : croiser la condition avec la valeur actuelle du champ corrigé, repérer les cas ambigus.

```sql
SELECT doc_type::text, count(*) FROM publications
WHERE title_normalized LIKE 'additional file%' GROUP BY 1;
```

Si l'audit révèle un faux positif probable, durcir la condition (liste blanche plus étroite, signal additionnel).

### 3. Implémentation

#### 3.1 Membre de l'enum

Dans `rules.py`, ajouter un membre à `MetadataCorrectionRule`. Convention : `INPUT_CONDITION_TO_OUTPUT` (`THESES_FR_URL_TO_THESIS`, `JOURNAL_TYPE_MEDIA_TO_MEDIA`, `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`). Le membre est la provenance inscrite dans `corrections.<champ>.corrected_by`.

#### 3.2 Entrée dans `_RULES`

```python
MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET: {
    "applies_to": {
        "doc_type": frozenset({"article", "other"}),
        "title_prefix_normalized": _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES,
    },
    "applies_correction": {"doc_type": "dataset"},
},
```

Les prédicats admis sont les clés du TypedDict `_AppliesTo`. Une clé qui nomme un champ de `MetadataForCorrection` teste l'égalité. Les autres clés ont leur branche dans `_check_predicate`. Préférer un prédicat réutilisable à un prédicat sur-spécialisé.

#### 3.3 Position dans le dict (priorité)

L'ordre d'insertion de `_RULES` est la priorité : `_correct_field` renvoie la première règle qui s'applique.

#### 3.4 Constantes locales

Les motifs réutilisés (regex, tuples de préfixes) sont des constantes de module préfixées par `_`, au-dessus de `_RULES`. Leur commentaire dit le choix de leur forme (« ensemble ciblé plutôt que `'supplementary '` large, pour éviter les faux positifs »). Une liste blanche triviale utilisée une seule fois reste dans l'entrée.

#### 3.5 Champ corrigé absent de `_AppliesCorrection`

Pour corriger un autre champ :

1. ajouter la clé à `_AppliesCorrection`, le champ à `CorrectedFields`, et son `_correct_field` dans `effective_metadata` ;
2. ajouter sa clé à `CorrectionKey` et à `UNARY_KEYS` ([`corrections.py`](../../domain/source_records/corrections.py)) ;
3. écrire la valeur corrigée et sa trace dans `correct_source_record`, et le champ dans `CorrectedSourceRecord` ;
4. ajouter la colonne à la comparaison de `compute_update` (`correct_unary.py`), à `CorrectionUpdate` et à `_CORRECTABLE_COLUMNS` (`metadata_correction_queries.py`), dans [`correction/`](../../pipeline/transformation/publications/correction/).

### 4. Étendre `MetadataForCorrection` si nécessaire

Si le fait est absent de `MetadataForCorrection` :

1. ajouter le champ à `MetadataForCorrection`, avec `None` pour défaut ;
2. ajouter son expression SQL à `_FACTS` ([`metadata_correction_queries.py`](../../pipeline/transformation/publications/correction/metadata_correction_queries.py)), sous le nom du champ. Une assertion vérifie que `_FACTS` couvre les champs de `MetadataForCorrection` ;
3. si le prédicat teste autre chose que l'égalité, ajouter sa clé à `_AppliesTo` et sa branche dans `_check_predicate` ;
4. si la publication connaît ce fait, l'ajouter à `MetadataForCorrection.for_publication` et à son appel dans `_apply_canonical_doc_type_correction` ([`consolidation.py`](../../pipeline/transformation/publications/consolidation.py)).

### 5. Tests

Dans [`test_correction.py`](../../tests/unit/domain/source_records/test_correction.py), une classe `TestNomDeLaRègle` :

- **Cas positif** : le signal est présent → `effective_metadata` pose la correction avec la bonne valeur et le bon membre.
- **Cas no-op** : la valeur courante est déjà la cible → aucune correction.
- **Cas négatif** : le signal est absent → aucune correction.
- **Robustesse** : variations attendues du signal (casse, espaces, accents).
- **Cascade** : combinaison avec une règle plus prioritaire → la prioritaire gagne.

### 6. Hooks admin (seulement si un fait lu est éditable par l'admin)

Si la règle lit un champ que l'admin modifie dans l'interface (`journal.journal_type`, `journal.oa_model`) :

1. **Recalcul des corrections** : `correct_journal_records` ([`requalify_journal.py`](../../pipeline/transformation/publishing/journals/requalify_journal.py)) recalcule et persiste les corrections des enregistrements sources de la revue, puis `refresh_from_sources` recalcule les publications concernées.
2. **Service de requalification** dans `application/services/<table>/core.py`, sur le modèle de [`requalify_publications_for_journal`](../../application/services/journals/core.py) : recalcul, rafraîchissement et audit. La prévisualisation l'exécute dans un `SAVEPOINT` annulé.
3. **Lecture** : `PublicationStore.find_ids_by_<clé>` (`pipeline/transformation/publications/store.py`).
4. **Endpoints API** : `POST /api/<table>/{id}/<champ>-change-impact`, avec la valeur proposée dans le corps → `{count: N}` (prévisualisation) ; `PUT /api/<table>/{id}` détecte le changement et déclenche la requalification dans la même transaction.
5. **Modèles Pydantic** dédiés dans `interfaces/api/models/<table>.py` (jamais `body: dict`).
6. **Frontend** : appel de prévisualisation à l'enregistrement, modale de confirmation, **message générique** sur le nombre de publications recalculées. L'agrégation dépend de toutes les sources, et seulement en partie du champ modifié.

### 7. Rattrapage du stock

Une règle ajoutée à `_RULES` s'applique au prochain passage de `metadata_correction`, qui recalcule tous les enregistrements sources : `run_pipeline --only metadata_correction`. Enchaîner `run_pipeline --only publications` pour résoudre à nouveau les enregistrements sources marqués `keys_dirty` et rafraîchir leurs publications.

### 8. Documentation

Le catalogue des règles actives est le dict `_RULES` lui-même, avec le commentaire de motivation au-dessus de chaque entrée. Si la règle illustre une combinaison de signal et de correction absente des exemples ci-dessous, compléter le § Exemples.

## Corrections par groupe de DOI

Les règles de `_RULES` décident d'un enregistrement source **seul**. D'autres corrections examinent le **groupe d'enregistrements sources qui partagent un DOI** et en déduisent le DOI de chaque membre. Deux familles : **convergence** (les versions DataCite d'une même œuvre convergent sur le DOI concept) et **divergence** (le DOI partagé par des œuvres distinctes est retiré du mauvais côté, pour éviter leur fusion).

La décision est dans `resolve_cluster_doi_corrections` ([`shared_doi.py`](../../domain/source_records/metadata_correction/shared_doi.py)), pure et indépendante de la source. La sous-étape `correct_by_cluster.py` regroupe par DOI d'avant correction, demande au domaine le DOI de chaque membre, remplace ou retire le DOI, et inscrit la valeur d'avant correction avec le cas `DoiClusterCase` pour provenance.

Pour un cas supplémentaire : ajouter un membre à `DoiClusterCase` (l'énoncé métier dans son commentaire) et la branche correspondante dans `resolve_cluster_doi_corrections`.

## Exemples concrets

### Règle propre à l'enregistrement source, un critère

**`THESES_FR_URL_TO_THESIS`** — URL theses.fr, sans `journal_id` ⇒ `doc_type = thesis`.

- Faits : `urls` et `journal_id_present: False`. Un enregistrement source theses.fr *avec* revue est un article publié, traité par `THESIS_WITH_JOURNAL_TO_ARTICLE`.
- Hook admin : non (URL non éditable).

### Règle propre à l'enregistrement source, plusieurs critères avec liste blanche

**`TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`** — titre qui commence par un préfixe de `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` et `doc_type ∈ {article, other}` ⇒ `dataset`.

- Ensemble de préfixes ciblé : `'supplementary '` seul toucherait « Supplementary roles of X ». Les types de référence sont épargnés.

### Règle sur la revue, éditable par l'admin

**`JOURNAL_TYPE_MEDIA_TO_MEDIA`** — `journal.journal_type = 'media'` ⇒ `doc_type = media`.

- Fait : `journal_type`, joint depuis `journals`.
- Hook admin : oui. Service [`requalify_publications_for_journal`](../../application/services/journals/core.py), endpoint `POST /api/journals/{id}/type-change-impact`, requalification dans le `PUT`, modale frontend.

## Anti-patterns

- **Corriger à la normalisation** : la valeur de la source est perdue et la correction devient irréversible. La correction est une règle de `rules.py`, persistée par la phase `metadata_correction`.
- **Encoder la règle en SQL** (vue, trigger, UPDATE non tracé) : la trace `corrections.<champ>.corrected_by` et la valeur d'avant correction sont perdues.
- **Cascade implicite** : deux règles sur le même champ sans ordre explicite. L'ordre des entrées de `_RULES` fait foi.
- **Hook admin sans service** : déclencher `refresh_from_sources` depuis le router. Le service propriétaire (`application/services/<table>/`) est l'unique point d'écriture des publications.
