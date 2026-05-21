# Chantier — DOI Registration Agencies & DataCite

Commencé le 2026-04-28

## Contexte

Un DOI est enregistré auprès d'une **Registration Agency** (RA) — chaque RA gère un sous-ensemble disjoint des préfixes DOI :

- **Crossref** : la majorité des articles de revue et chapitres d'ouvrage.
- **DataCite** : datasets, software, preprints (HAL via DOI propre<!--TODO: what?-->, Zenodo, figshare), thèses (theses.fr distribue des DOI DataCite), repositories institutionnels.
- **mEDRA / JaLC / Airiti / Op.cit. / etc.** : volumes négligeables côté UCA.

Aujourd'hui, `fetch_missing_doi --target crossref` interroge l'API CrossRef pour **tous** les DOI manquants en staging CrossRef, sans tenir compte de leur RA. Sur les 12 045 DOIs traités le 2026-04-28 :
- une part significative renvoie 404 (DOI non Crossref) — appels inutiles, statistiques `not_found` artificiellement gonflées, pollution du staging avec des stubs `not_found=TRUE`.
- les DOIs DataCite (Zenodo, theses.fr, etc.) restent invisibles côté métadonnées : on a le DOI mais aucune métadonnée enrichie hors HAL/OpenAlex.

Ce chantier traite les deux faces du problème : **savoir** d'où vient chaque DOI, puis **exploiter** cette information pour économiser les appels CrossRef et ouvrir DataCite comme nouvelle source.

Les préfixes DOI mappés aux `publishers` (et indirectement aux `journals`) serviront aussi au dédoublonnage des éditeurs/revues et à la détection des métadonnées incohérentes issues des sources (DOI vs `journal`, DOI vs `doc_type`…). Cf chantier `METIER_publishers-journals.md`.

## Périmètre fonctionnel

### Inclus

- Table dédiée `doi_prefixes` indexée sur le **préfixe** DOI (`10.xxxx`) — un préfixe = un registrant = une RA permanente, donc un seul lookup par préfixe (vs un par DOI).
- Phase pipeline `resolve_doi_prefixes` qui pour chaque préfixe inconnu interroge `doi.org/ra` une fois et stocke le résultat. Bootstrap progressif, sans bootstrap massif.
- Mapping prefix → publisher : pour les préfixes Crossref, l'endpoint `api.crossref.org/prefixes/{prefix}` renvoie le `name` du publisher → matching contre `publishers.name_normalized`. La table `doi_prefixes` devient la source canonique du mapping prefix → publisher.
- Retrait de la colonne `publishers.doi_prefix` (limitée à un seul préfixe par publisher) — remplacée par la jointure sur `doi_prefixes.publisher_id`.
- Filtrage de `get_cross_import_dois("crossref")` : skip les DOIs dont le préfixe a `ra != 'Crossref'` (et `ra IS NULL` accepté pour traiter les nouveaux préfixes en best-effort).
- Nouvelle source `datacite` : extracteur DOI-driven, normalizer, mapping `doc_type`, ajout à `SOURCE_PRIORITY`, `ALL_SOURCES`, `DOI_SEARCHABLE_SOURCES`, et à l'enum SQL `source_type`.
- Affichage UI : icône DataCite dans la cellule "Sources" des tableaux publi, facette source.

### Exclus

- Ingestion des autres RAs (mEDRA, JaLC, Airiti, Op.cit.). Volumes UCA négligeables, ROI nul.
- Discovery via DataCite par affiliation. DataCite n'a pas d'index affiliation/ROR exploitable, on reste DOI-driven.
- Refetch périodique de la RA. Un préfixe ne change pas de RA en pratique (assignation permanente) — résolution unique au premier passage par préfixe, ré-essai uniquement si l'appel précédent a échoué.
- Modification de `journals.doi_prefix` — concept différent (pattern de matching journal incluant un suffixe discriminant comme `10.1038/s41586` pour Nature), à conserver tel quel.

## Architecture cible

### Tables

- **`doi_prefixes`** (à créer) :
  ```sql
  CREATE TABLE doi_prefixes (
      prefix text PRIMARY KEY,                    -- '10.1038', '10.5281', etc.
      ra text NOT NULL,                           -- 'Crossref', 'DataCite', 'mEDRA', 'JaLC', 'KISTI', 'Airiti', 'OP', 'unknown'
      publisher_id integer REFERENCES publishers(id) ON DELETE SET NULL,
      publisher_name_raw text,                    -- nom brut depuis api.crossref.org/prefixes/{prefix}
      publisher_name_normalized text,             -- normalize_text(publisher_name_raw), pour re-match différé
      crossref_member_id integer,                 -- 'member' renvoyé par api.crossref.org/prefixes/{prefix}
      fetched_at timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX idx_doi_prefixes_ra ON doi_prefixes (ra);
  CREATE INDEX idx_doi_prefixes_publisher ON doi_prefixes (publisher_id) WHERE publisher_id IS NOT NULL;
  CREATE INDEX idx_doi_prefixes_publisher_name_normalized
      ON doi_prefixes (publisher_name_normalized) WHERE publisher_id IS NULL;
  ```
  - **Préfixe en PK** : un préfixe = un registrant = une RA permanente. ~quelques centaines de préfixes distincts pour un corpus UCA (vs des millions de DOIs). Lookup compact, refresh trivial.
  - **`ra='unknown'`** : préfixe résolu par doi.org mais avec une RA hors du sous-ensemble nommé (les 8 RAs connues) — on stocke pour ne pas réinterroger.
  - **Préfixe non insérable** : si tous les DOI samples d'un préfixe échouent (404, `"DOI Not Found"`, erreur réseau), **on n'insère pas** la row. Le préfixe reste absent de `doi_prefixes` et sera retenté au prochain run du pipeline. Idempotent, pas de sentinelle « unresolved ».
  - **`publisher_id` nullable** : peut rester NULL pour les préfixes DataCite (pas d'équivalent éditeur académique pour Zenodo, figshare, etc.) ou les Crossref dont le `name` ne matche pas une row `publishers` existante. Dans ce dernier cas, `publisher_name_normalized` reste rempli pour permettre un re-match différé (job de réconciliation ou nouvelle création de publisher via OpenAlex).
  - **`crossref_member_id`** : info observée à l'instant de la résolution. Co-stockée par préfixe plutôt que sur `publishers` ; les préfixes d'un même publisher partageront la même valeur (cohérence vérifiable via `SELECT DISTINCT crossref_member_id FROM doi_prefixes WHERE publisher_id = X`).
- **`publishers.doi_prefix` (à supprimer)** : colonne devenue redondante avec `doi_prefixes`. Retrait après migration des données existantes.
- **`source_type` enum (modif)** : ajout de `'datacite'`.

### Code

- **`infrastructure/sources/datacite/`** : client API REST (https://api.datacite.org), polite pool si documenté, retry, gestion 404 → `not_found=TRUE`. Modèle calqué sur `crossref/fetch_missing_doi.py`.
- **`infrastructure/sources/doi_prefixes/`** (ou intégré à `infrastructure/sources/common.py`) : client `doi.org/ra` (un appel par DOI sample) + client `api.crossref.org/prefixes/{prefix}` pour récupérer `name` et `member` du publisher.
- **`application/pipeline/resolve_doi_prefixes.py`** : orchestrateur de la phase pipeline. Pour chaque préfixe DOI absent de `doi_prefixes` :
  1. Récupère jusqu'à N DOI samples du staging pour ce préfixe (N=3 par défaut).
  2. Tente `doi.org/ra` dans l'ordre ; premier 200 avec RA ≠ `"DOI Not Found"` → on garde la valeur.
  3. Si tous les samples échouent → on n'insère pas, retry au run suivant.
  4. Si RA = `"Crossref"` → appel `api.crossref.org/prefixes/{prefix}` pour `name` + `member`, normalisation via `normalize_text`, matching contre `publishers.name_normalized`.
  5. Insert avec `publisher_id` (ou NULL si pas de match), `publisher_name_raw`, `publisher_name_normalized`, `crossref_member_id`.
- **`application/pipeline/normalize/normalize_datacite.py`** + ports + queries : normalizer DataCite (mapping resourceTypeGeneral → doc_type, extraction creators, dates, container, identifiers).
- **`infrastructure/sources/common.py::get_cross_import_dois`** : LEFT JOIN sur `doi_prefixes` via `split_part(doi, '/', 1) = doi_prefixes.prefix`, filtrage `ra = target_ra OR ra IS NULL` (où `target_ra='Crossref'` pour cible crossref, `'DataCite'` pour cible datacite).
- **Modifications dans `domain/`** :
  - `domain/sources.py` : ajout de `"datacite"` à `ALL_SOURCES`, `DOI_SEARCHABLE_SOURCES`, et insertion dans `SOURCE_PRIORITY` (position à arbitrer, cf. décisions à prendre).
  - `domain/doc_types.py` : entrée `"datacite"` dans `_SOURCE_MAPS` (mapping resourceTypeGeneral DataCite → enum canonique).
- **Adaptation des consommateurs de `publishers.doi_prefix`** :
  - API : `interfaces/api/routers/publishers.py` (SELECT + UPDATE) et models Pydantic associés.
  - Frontend admin : `interfaces/frontend/src/routes/admin/publishers/+page.svelte` (suppression du champ d'édition, ajout d'une cellule "préfixes" qui liste les préfixes via JOIN sur `doi_prefixes`).
- **Frontend publi** : icône DataCite dans `interfaces/frontend/src/lib/utils.ts` (URL builder), composants tableau publi.

### Place dans le pipeline

Nouvel ordre dans `run_pipeline.py` :

```
extract → cross_imports (fetch_missing_hal_id + fetch_missing_doi) → normalize → resolve_doi_prefixes → publications → …
```

`resolve_doi_prefixes` se lance **après normalize** pour deux raisons :

1. `cross_imports` enchaîne `fetch_missing_hal_id` puis `fetch_missing_doi` — le premier peut introduire de nouveaux DOIs en staging via les refetch HAL. Résoudre avant `fetch_missing_doi` raterait ces DOIs et obligerait à un second passage.
2. `normalize` crée les publishers via `find_or_create_publisher` (depuis crossref, openalex). Matcher `publisher_name_normalized` contre `publisher_name_forms` **après** normalize donne un vrai match au lieu d'un best-effort qui aurait laissé `publisher_id NULL` à reconcilier plus tard.

**Conséquence sur le filtre `fetch_missing_doi --target crossref` :** les préfixes inédits d'un run donné ne sont résolus qu'à la fin de ce run, donc le `fetch_missing_doi` du run suivant en profite. Au run N le filtre couvre tout ce qui était déjà connu (seed + runs précédents) ; au run N+1, les préfixes ajoutés au run N sont eux aussi filtrés. Idempotent : ne ré-interroge que les préfixes absents de `doi_prefixes`. Volume des appels API minuscule (un appel par nouveau préfixe).

## Phases d'implémentation

### Phase 0 — Spike & validation
- [x] Inventaire des préfixes en staging (`SELECT split_part(doi, '/', 1) AS prefix, COUNT(*) FROM staging WHERE doi IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 50`).
- [x] Pour chaque préfixe distinct, requête `doi.org/ra` (un seul appel par préfixe via un DOI échantillon) → distribution des RAs.
- [x] Sample d'~70 DOIs DataCite stratifiés par doc_type, requête API DataCite, évaluation des champs (creators avec ORCID, affiliations, container, relatedIdentifiers, types).
- [x] Volume CrossRef économisé par le filtre : ≈ 12 % d'appels (3 000 / 24 000) + élimination des stubs `not_found=TRUE` polluants.
- **Livrable** : note `docs/chantiers/doi-prefixes-spike.md` + script `interfaces/cli/oneshot/doi_prefixes_spike.py`. **Phase 1 = GO. Phase 2 = GO** avec exclusion explicite du préfixe `10.60692` (OpenAlex generated DOIs).

### Phase 1 — Table `doi_prefixes` + filtre CrossRef + retrait `publishers.doi_prefix`
- [x] Migration Alembic `0019_doi_prefixes` : `CREATE TABLE doi_prefixes` + index.
- [x] One-shot `interfaces/cli/oneshot/seed_doi_prefixes.py` : seed initial depuis `docs/chantiers/doi-prefixes-spike-data/ra_cache.json` + `publisher_cache.json` (871 préfixes résolus + 711 mappings publisher). Évite ~900 appels API redondants au premier run prod. Lancé une seule fois par Laura après la migration.
- [x] Client `doi.org/ra` + client `api.crossref.org/prefixes/{prefix}` dans `infrastructure/sources/doi_prefixes/`.
- [x] Phase pipeline `resolve_doi_prefixes` : retry multi-DOI (N=3), résolution RA, mapping publisher pour Crossref, insert dans `doi_prefixes`. Préfixe non résolvable → pas d'insert (retry au run suivant).
- [x] Wiring dans `run_pipeline.py` (`--only resolve_doi_prefixes`, `--from resolve_doi_prefixes`), placé **après normalize** (cf. section Place dans le pipeline).
- [x] Modification `get_cross_import_dois` : LEFT JOIN sur `doi_prefixes` via `split_part(doi, '/', 1)`, filtre `ra = 'Crossref' OR ra IS NULL` pour la cible crossref. NULL accepté pour traiter les préfixes pas encore résolus en best-effort.
- [x] Adapter API/UI publishers : retirer le champ `doi_prefix` côté Pydantic + admin Svelte ; ajouter une vue "préfixes" en lecture seule via JOIN sur `doi_prefixes`.
- [x] Migration Alembic `drop_publishers_doi_prefix` : `ALTER TABLE publishers DROP COLUMN doi_prefix` (après que les consommateurs côté API/UI aient été adaptés).
- **Livrable** : appels CrossRef ciblés, `doi_prefixes` peuplée, mapping prefix → publisher many-to-one en place, pas encore de DataCite ingérée.

### Phase 2 — Source DataCite (sous réserve phase 0 favorable)
- [ ] Migration : ajout de `'datacite'` à l'enum SQL `source_type`.
- [ ] `domain/sources.py` : ajout aux constantes (`ALL_SOURCES`, `DOI_SEARCHABLE_SOURCES`, `SOURCE_PRIORITY`).
- [ ] `domain/doc_types.py` : `_SOURCE_MAPS["datacite"]` (mapping resourceTypeGeneral → enum canonique).
- [ ] Client API DataCite + adapter `fetch_missing_doi` (extends `AsyncFetchMissingDoiAdapter`), rate limits prudents.
- [ ] Filtre `get_cross_import_dois("datacite")` : `ra = 'DataCite'` via JOIN sur `doi_prefixes`, **avec exclusion explicite du préfixe `10.60692`** (DOIs synthétiques générés par OpenAlex pour ses propres publis sans DOI éditeur — métadonnées DataCite vides ou strictement redondantes avec ce qu'OpenAlex fournit déjà).
- [ ] Wiring dans `run_pipeline.py` (cible datacite dans `fetch_missing_doi`).
- [ ] Normalizer DataCite (ports + queries + orchestrator + CLI), alimente `source_publications` / `source_authorships`.
- [ ] Tests d'intégration.
- **Livrable** : `source_publications` peuplée pour les DOIs DataCite, accessible via le pipeline normal.

### Phase 3 — UI & cohérence finale
- [ ] Icône DataCite dans la cellule "Sources" des tableaux publi (publications / theses / detail / personnes / labos).
- [ ] Facette source DataCite dans `SourceFilterToggle`.
- [ ] Endpoint admin (optionnel) pour visualiser la distribution par RA et auditer les préfixes `unknown` / `publisher_id IS NULL`.
- **Livrable** : DataCite visible dans l'UI au même titre que les autres sources.

## Décisions actées

1. **Granularité = préfixe DOI, pas DOI individuel**.
   - Raison : un préfixe = un registrant = une RA permanente. Stocker per-DOI dupliquerait l'info pour des millions de lignes alors qu'un corpus UCA n'a typiquement que quelques centaines de préfixes distincts. Une table compacte côté préfixe est largement plus propre et économe en API calls (un appel par nouveau préfixe au lieu d'un par DOI).
2. **Table unifiée `doi_prefixes` qui porte aussi le mapping vers `publishers`**.
   - Raison : la même information préfixe → registrant fait à la fois `prefix → ra` et `prefix → publisher`. Une seule table évite la duplication. Bonus : mapping many-to-one (un publisher peut avoir N préfixes — Springer/Nature en ont plusieurs) que la colonne mono-valeur `publishers.doi_prefix` ne pouvait pas représenter. Retrait de cette colonne en même temps que la création de `doi_prefixes`.
3. **Résolution paresseuse via `doi.org/ra` + `api.crossref.org/prefixes/{prefix}`**.
   - Raison : pas de bootstrap massif (~25k préfixes Crossref), pas de cache de listes externes à maintenir. On résout au fil de l'eau les préfixes inconnus rencontrés dans le staging, et la table se peuple à mesure que de nouveaux corpus arrivent.
4. **Scope = filtre CrossRef + retrait `publishers.doi_prefix` + ingestion DataCite** (option (b) discutée le 2026-04-28, étendue le 2026-04-28 pour intégrer le retrait `publishers.doi_prefix`).
   - Phase 1 (filtre + retrait) ship indépendamment de Phase 2 (DataCite). Phase 2 conditionnée à phase 0 (spike DataCite favorable).

## Décisions à prendre

1. **Position de DataCite dans `SOURCE_PRIORITY`** : à arbitrer en phase 2, après spike. Hypothèse : DataCite fait autorité pour les DOIs DataCite (datasets, theses, preprints) au même titre que CrossRef pour les Crossref. Comme un DOI a une seule RA, les deux ne s'arbitrent jamais sur la même publi — la position relative entre CrossRef et DataCite n'a en pratique aucun effet. À mettre symétriquement à CrossRef (2ᵉ ou 3ᵉ position).
2. **Politique de réinterrogation `ra='unknown'`** : ré-essayer après N jours (backoff) ou jamais ? Recommandation : jamais par défaut, refetch manuel possible via flag CLI. Les préfixes non insérés (samples tous échoués) sont eux retentés à chaque run, sans politique particulière.
3. **Politique de purge des `not_found=TRUE` côté CrossRef** post-filtre : les DOIs DataCite déjà marqués `not_found=TRUE` dans `staging` (legacy avant ce chantier) restent comme stubs. Choix : (a) les laisser, ou (b) un script one-shot qui les supprime pour permettre une éventuelle re-tentative sur DataCite source.
4. **Mapping doc_types DataCite** : à concevoir en phase 0 avec exemples réels. La taxonomie DataCite (`resourceTypeGeneral` : Dataset, Software, Preprint, Text, JournalArticle, Audiovisual, etc.) est plus large que CrossRef. Probable mapping :
   - `Dataset` → `dataset`
   - `Software` → `software`
   - `Preprint` → `preprint`
   - `JournalArticle` → `article`
   - `Text` (generic) → exploitation du `resourceType` libre pour deviner, fallback `other`.
5. **Matching publisher_name_raw → publisher existant** : seuils et règles (exact normalized, fuzzy, manuel ?). Recommandation : commencer par exact-match sur `name_normalized`, fallback `publisher_id NULL` pour traitement admin manuel.

## Risques & open questions

- **Couverture DataCite UCA inconnue avant spike**. Si l'apport métadonnées s'avère négligeable (la plupart des DOIs DataCite sont déjà dans HAL avec métadonnées équivalentes), la phase 2 peut être abandonnée et seul le filtre CrossRef sera retenu — gain immédiat sans coût.
- **Rate limits doi.org/ra** non documentés explicitement. À mesurer en phase 0. Volume négligeable de toute façon (un appel par nouveau préfixe).
- **Évolutivité du mapping doc_types DataCite** : `resourceTypeGeneral` est une enum officielle stable, mais `resourceType` libre (texte) côté éditeur. Privilégier le general, fallback sur le libre.
- **Préfixe nouveau pendant un run** : si un nouveau préfixe DOI apparaît entre la phase `resolve_doi_prefixes` et `fetch_missing_doi`, il sera traité avec `ra IS NULL` (best-effort, on tente CrossRef). Une seconde passe le résoudra. Acceptable.
- **Migration `publishers.doi_prefix` → `doi_prefixes`** : couverture des données existantes incomplète si la colonne n'a pas été remplie systématiquement (la user indique qu'elle n'avait pas commencé). Migration ne portera que sur les rows non-NULL.

## Liens

- doi.org RA API : <https://www.doi.org/factsheets/DOIProxy.html#rest-api> (endpoint `/ra/{doi[,doi,…]}`)
- CrossRef Prefixes API : <https://api.crossref.org/swagger-ui/index.html#/Prefixes>
- DataCite REST API : <https://support.datacite.org/docs/api>
- DataCite metadata schema : <https://schema.datacite.org/>
- chantier crossref : `docs/chantiers/crossref.md` (architecture jumelle)
