# Chantier — DOI Registration Agencies & DataCite
Commencé le 2026-04-28

## Contexte

Un DOI est enregistré auprès d'une **Registration Agency** (RA) — chaque RA gère un sous-ensemble disjoint des préfixes DOI :

- **Crossref** : la majorité des articles de revue et chapitres d'ouvrage.
- **DataCite** : datasets, software, preprints (HAL via DOI propre, Zenodo, figshare), thèses (theses.fr distribue des DOI DataCite), repositories institutionnels.
- **mEDRA / JaLC / Airiti / Op.cit. / etc.** : volumes négligeables côté UCA.

Aujourd'hui, `fetch_missing_doi --target crossref` interroge l'API CrossRef pour **tous** les DOI manquants en staging CrossRef, sans tenir compte de leur RA. Sur les 12 045 DOIs traités le 2026-04-28 :
- une part significative renvoie 404 (DOI non Crossref) — appels inutiles, statistiques `not_found` artificiellement gonflées, pollution du staging avec des stubs `not_found=TRUE`.
- les DOIs DataCite (Zenodo, theses.fr, etc.) restent invisibles côté métadonnées : on a le DOI mais aucune métadonnée enrichie hors HAL/OpenAlex.

Ce chantier traite les deux faces du problème : **savoir** d'où vient chaque DOI, puis **exploiter** cette information pour économiser les appels CrossRef et ouvrir DataCite comme nouvelle source.

## Périmètre fonctionnel

### Inclus

- Table dédiée `doi_registration_agencies` stockant la RA par DOI.
- Phase pipeline `resolve_doi_ra` qui interroge l'API doi.org/ra (batchée) et alimente la table.
- Filtrage de `get_cross_import_dois("crossref")` : skip les DOIs dont `ra != 'Crossref'` (et `ra != NULL` pour traiter les inconnus en best-effort).
- Nouvelle source `datacite` : extracteur DOI-driven, normalizer, mapping `doc_type`, ajout à `SOURCE_PRIORITY`, `ALL_SOURCES`, `BIBLIO_SOURCES`, et à l'enum SQL `source_type`.
- Affichage UI : icône DataCite dans la cellule "Sources" des tableaux publi, facette source.

### Exclus

- Ingestion des autres RAs (mEDRA, JaLC, Airiti, Op.cit.). Volumes UCA négligeables, ROI nul.
- Discovery via DataCite par affiliation. DataCite n'a pas d'index affiliation/ROR exploitable, on reste DOI-driven.
- Refetch périodique de la RA. La RA d'un DOI ne change pas en pratique (sauf retraits exceptionnels) — résolution unique au premier passage, ré-essai uniquement si l'appel précédent a échoué.

## Architecture cible

### Tables

- **`doi_registration_agencies`** (à créer) :
  ```sql
  CREATE TABLE doi_registration_agencies (
      doi text PRIMARY KEY,
      ra text NOT NULL,           -- 'Crossref', 'DataCite', 'mEDRA', 'unknown', 'not_found'
      fetched_at timestamptz NOT NULL DEFAULT now()
  );
  CREATE INDEX idx_doi_ra ON doi_registration_agencies (ra);
  ```
  - **DOI en PK** : la RA est une propriété du DOI, source-agnostique. Pas de duplication entre `staging` et `source_publications`.
  - **`ra='unknown'`** : DOI résolu par doi.org mais avec une RA hors du sous-ensemble qu'on traite — on stocke pour ne pas réinterroger.
  - **`ra='not_found'`** : doi.org renvoie "DOI does not exist" — DOI invalide, à signaler côté UI éventuellement.
- **`source_type` enum (modif)** : ajout de `'datacite'`.
- **Pas de nouvelle table pour DataCite** : `source_publications` / `source_authorships` / `source_persons` accueillent les rows avec `source='datacite'`, sur le modèle CrossRef (cf. chantier crossref.md).

### Code

- **`infrastructure/sources/datacite/`** : client API REST (https://api.datacite.org), polite pool si documenté, retry, gestion 404 → `not_found=TRUE`. Modèle calqué sur `crossref/fetch_missing_doi.py`.
- **`infrastructure/sources/doi_ra/`** (ou intégré à `infrastructure/sources/common.py`) : client doi.org/ra batché.
- **`application/pipeline/resolve_doi_ra.py`** : orchestrateur de la phase pipeline.
- **`application/pipeline/normalize/normalize_datacite.py`** + ports + queries : normalizer DataCite (mapping resourceTypeGeneral → doc_type, extraction creators, dates, container, identifiers).
- **`infrastructure/sources/common.py::get_cross_import_dois`** : ajout d'une jointure / sous-requête conditionnelle pour exclure les DOIs avec `ra != target_ra` (où `target_ra='Crossref'` pour cible crossref, `'DataCite'` pour cible datacite).
- **Modifications dans `domain/`** :
  - `domain/sources.py` : ajout de `"datacite"` à `ALL_SOURCES`, `BIBLIO_SOURCES`, et insertion dans `SOURCE_PRIORITY` (position à arbitrer, cf. décisions à prendre).
  - `domain/doc_types.py` : entrée `"datacite"` dans `_SOURCE_MAPS` (mapping resourceTypeGeneral DataCite → enum canonique).
- **Frontend** : icône DataCite dans `interfaces/frontend/src/lib/utils.ts` (URL builder), composants tableau publi.

### Place dans le pipeline

Nouvel ordre dans `run_pipeline.py` :

```
extract → resolve_doi_ra → fetch_missing_doi (par cible : crossref, datacite, hal, oa, …) → normalize → …
```

`resolve_doi_ra` se lance **après** extract (pour avoir tous les DOIs en staging) et **avant** `fetch_missing_doi` pour qu'il filtre proprement par RA. Idempotent : ne ré-interroge que les DOIs sans entrée dans `doi_registration_agencies`.

## Phases d'implémentation

### Phase 0 — Spike & validation
- [ ] Inventaire des DOIs en staging par préfixe (`SELECT split_part(doi, '/', 1) AS prefix, COUNT(*) FROM staging WHERE doi IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 50`).
- [ ] Sample d'~500 DOIs représentatifs, requête doi.org/ra batchée, mesurer la distribution des RAs.
- [ ] Sample d'~100 DOIs DataCite, requête API DataCite, évaluer :
  - Format de réponse (JSON-API vs Crossref REST différent).
  - Couverture sur theses.fr / Zenodo / HAL / dépôts univ.
  - Champs exploitables (creators, contributors, dates, container, relatedIdentifiers, rightsList, types).
  - ORCID dans les creators (article-level si présent).
- [ ] Estimer le volume CrossRef qui sera économisé après le filtre RA.
- **Livrable** : note `docs/chantiers/datacite-spike.md` + script `interfaces/cli/datacite_spike.py`. Décision go/no-go sur la phase 2.

### Phase 1 — Résolution RA + filtre CrossRef
- [ ] Migration : `CREATE TABLE doi_registration_agencies` (DDL → migration via `db/migrate.py`).
- [ ] Client doi.org/ra (batch ~50 DOIs / req).
- [ ] Phase pipeline `resolve_doi_ra` : lit les DOIs en staging absents de `doi_registration_agencies`, batche, insère.
- [ ] Wiring dans `run_pipeline.py` (`--only resolve_doi_ra`, `--from resolve_doi_ra`).
- [ ] Modification `get_cross_import_dois` : LEFT JOIN sur `doi_registration_agencies`, filtre `ra IN ('Crossref', NULL) OR ra IS NULL` pour la cible crossref. NULL accepté pour ne pas bloquer si la phase n'a pas encore tourné.
- [ ] Tests : intégration sur petit lot mixte (Crossref + DataCite + Zenodo).
- [ ] Lancer une fois en prod, mesurer la réduction du volume CrossRef et la disparition des 404.
- **Livrable** : appels CrossRef ciblés, `doi_registration_agencies` peuplée, pas encore de DataCite ingérée.

### Phase 2 — Source DataCite (sous réserve phase 0 favorable)
- [ ] Migration : ajout de `'datacite'` à l'enum SQL `source_type`.
- [ ] `domain/sources.py` : ajout aux constantes (`ALL_SOURCES`, `BIBLIO_SOURCES`, `SOURCE_PRIORITY`).
- [ ] `domain/doc_types.py` : `_SOURCE_MAPS["datacite"]` (mapping resourceTypeGeneral → enum canonique).
- [ ] Client API DataCite + adapter `fetch_missing_doi` (extends `AsyncFetchMissingDoiAdapter`), rate limits prudents.
- [ ] Filtre `get_cross_import_dois("datacite")` : `ra = 'DataCite'`.
- [ ] Wiring dans `run_pipeline.py` (cible datacite dans `fetch_missing_doi`).
- [ ] Normalizer DataCite (ports + queries + orchestrator + CLI), alimente `source_publications` / `source_authorships` / `source_persons`.
- [ ] Tests d'intégration.
- **Livrable** : `source_publications` peuplée pour les DOIs DataCite, accessible via le pipeline normal.

### Phase 3 — UI & cohérence finale
- [ ] Icône DataCite dans la cellule "Sources" des tableaux publi (publications / theses / detail / personnes / labos).
- [ ] Facette source DataCite dans `SourceFilterToggle`.
- [ ] Endpoint admin (optionnel) pour visualiser la distribution par RA et auditer les DOIs `unknown` / `not_found`.
- **Livrable** : DataCite visible dans l'UI au même titre que les autres sources.

## Décisions actées

1. **Storage de la RA** : table dédiée `doi_registration_agencies` (vs colonne sur `staging` ou `source_publications`).
   - Raison : la RA est une propriété du DOI, indépendante de la source qui le connaît. Une table source-agnostique évite la duplication entre toutes les sources qui voient le même DOI.
2. **Résolution batchée via doi.org/ra** (vs liste de préfixes maintenue localement).
   - Raison : pas de cache de préfixes à maintenir, pas de risque de rater les nouveaux préfixes. L'API doi.org/ra est gratuite et batchable jusqu'à ~50 DOIs/req.
3. **Scope = filtre CrossRef + ingestion DataCite** (option (b) discutée le 2026-04-28).
   - Phase 1 (filtre) ship indépendamment de Phase 2 (DataCite). Phase 2 conditionnée à phase 0 (spike DataCite favorable).

## Décisions à prendre

1. **Position de DataCite dans `SOURCE_PRIORITY`** : à arbitrer en phase 2, après spike. Hypothèse : DataCite fait autorité pour les DOIs DataCite (datasets, theses, preprints) au même titre que CrossRef pour les Crossref. Comme un DOI a une seule RA, les deux ne s'arbitrent jamais sur la même publi — la position relative entre CrossRef et DataCite n'a en pratique aucun effet. À mettre symétriquement à CrossRef (2ᵉ ou 3ᵉ position).
2. **Politique de réinterrogation `ra='unknown'` / `ra='not_found'`** : ré-essayer après N jours (backoff) ou jamais ? Recommandation : jamais par défaut, refetch manuel possible via flag CLI.
3. **Affichage des DOIs `not_found`** : signaler côté UI ? Probablement oui (indicateur de qualité de données pour l'équipe biblio).
4. **Mapping doc_types DataCite** : à concevoir en phase 0 avec exemples réels. La taxonomie DataCite (`resourceTypeGeneral` : Dataset, Software, Preprint, Text, JournalArticle, Audiovisual, etc.) est plus large que CrossRef. Probable mapping :
   - `Dataset` → `dataset`
   - `Software` → `software`
   - `Preprint` → `preprint`
   - `JournalArticle` → `article`
   - `Text` (generic) → exploitation du `resourceType` libre pour deviner, fallback `other`.

## Risques & open questions

- **Couverture DataCite UCA inconnue avant spike**. Si l'apport métadonnées s'avère négligeable (la plupart des DOIs DataCite sont déjà dans HAL avec métadonnées équivalentes), la phase 2 peut être abandonnée et seul le filtre CrossRef sera retenu — gain immédiat sans coût.
- **Rate limits doi.org/ra** non documentés explicitement. À mesurer en phase 0. Polite par défaut : 1 req batchée par seconde.
- **Évolutivité du mapping doc_types DataCite** : `resourceTypeGeneral` est une enum officielle stable, mais `resourceType` libre (texte) côté éditeur. Privilégier le general, fallback sur le libre.
- **Compatibilité avec le chantier `source-persons` (en cours)** : DataCite n'a pas d'identifiant auteur stable côté creator → cas équivalent à OpenAlex/WoS, source synthétisée non écrite dans `source_persons` (cf. décision 2026-04-28). À refléter dans `_SOURCE_CONFIG` de `application/persons.py` lors de la phase 2.
- **Idempotence resolve_doi_ra** : si l'API doi.org renvoie une erreur transitoire, ne pas insérer `not_found` à tort. Distinguer erreurs réseau (retry) de "DOI does not exist" (statut explicite renvoyé par l'API).

## Liens

- doi.org RA API : <https://www.doi.org/factsheets/DOIProxy.html#rest-api> (endpoint `/ra/{doi[,doi,…]}`)
- DataCite REST API : <https://support.datacite.org/docs/api>
- DataCite metadata schema : <https://schema.datacite.org/>
- chantier crossref : `docs/chantiers/crossref.md` (architecture jumelle)
- chantier source-persons : `docs/chantiers/2026-04-28_source-persons.md` (impact sur DataCite côté `source_persons`)
