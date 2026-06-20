# Chantier — DOI Registration Agencies & DataCite

Commencé le 2026-04-28 - Terminé le 2026-06-20

## Contexte

Un DOI est enregistré auprès d'une **Registration Agency** (RA) — chaque RA gère un sous-ensemble disjoint des préfixes DOI :

- **Crossref** : la majorité des articles de revue, chapitres d'ouvrage, thèses françaises (via ABES).
- **DataCite** : datasets, software, preprints, theses, repositories institutionnels (Zenodo, figshare, theses.fr, NAKALA, INRAE, etc.).
- **mEDRA / JaLC / Airiti / OP / KISTI / CNKI** : volumes négligeables côté UCA (< 1 % au total).

Aujourd'hui, `fetch_missing_doi --target crossref` interroge l'API CrossRef pour **tous** les DOI manquants en staging CrossRef, sans tenir compte de leur RA. Le spike Phase 0 a chiffré : sur 23 948 DOIs ciblés, 12 % sont en réalité DataCite (404 systématique, pollution `not_found=TRUE`) et 8 % sur des RAs non résolues.

Ce chantier traite deux faces du problème : **savoir** d'où vient chaque DOI, puis **exploiter** cette information pour économiser les appels CrossRef, enrichir le mapping prefix → éditeur, et ingérer DataCite comme source à part entière (par DOI).

Les préfixes DOI mappés aux `publishers` (et indirectement aux `journals`) serviront aussi au dédoublonnage des éditeurs/revues et à la détection des métadonnées incohérentes (DOI/`journal`, DOI/`doc_type`). Cf. chantier `METIER_publishers-journals.md`.

### Périmètre

**Inclus** :
- Table `doi_prefixes` (PK = préfixe DOI), peuplée paresseusement via `doi.org/ra` + `api.crossref.org/prefixes/{p}` + `api.datacite.org/prefixes/{p}`.
- Phase pipeline `resolve_doi_prefixes` qui gère les deux RAs principales (Crossref, DataCite) et stocke un mapping prefix → publisher.
- Filtrage de `get_cross_import_dois` par RA : un appel CrossRef ne reçoit que des DOI Crossref, un appel DataCite que des DOI DataCite.
- Pour DataCite, intégration à deux niveaux : provider (parent organisation, va dans `publishers`) + client (repository spécifique, colonnes dédiées sur `doi_prefixes`).
- **Ingestion DataCite comme source, par DOI** (cross-import : DOI présent dans une autre source mais absent du staging DataCite), sur le même mode que Crossref.
- **Remplacement de la résolution concept/version Zenodo** par les `relatedIdentifiers` du payload DataCite.
- Affichage UI : icône DataCite dans les mêmes contextes que l'icône Crossref.

**Exclus** :
- Ingestion DataCite *affiliation-driven* ou *ORCID-driven* (sweep par affiliation / par identifiant chercheur). Piste réelle mais distincte — chantiers ultérieurs (cf. Questions ouvertes).
- Ingestion des autres RAs (mEDRA, JaLC, etc.). Volumes UCA négligeables.
- Facette « DOI » dans les filtres de listes (crossref / datacite / other / none). Hors scope (cf. Questions ouvertes).
- Refetch périodique de la RA. Un préfixe ne change pas de RA en pratique (assignation permanente).
- Modification de `journals.doi_prefix` — concept différent (pattern de matching incluant un suffixe discriminant comme `10.1038/s41586` pour Nature), conservé tel quel.

## Décisions

### Architecturales actées

1. **Granularité = préfixe DOI, pas DOI individuel** (pour la table RA/publisher). Un préfixe = un registrant = une RA permanente. Une table compacte côté préfixe (quelques centaines de rows pour le corpus UCA) est largement plus économe qu'un stockage per-DOI.

2. **Table unifiée `doi_prefixes`** qui porte à la fois `prefix → ra` et `prefix → publisher`. Évite la duplication. Mapping many-to-one (un publisher peut avoir N préfixes — Springer/Nature en a plusieurs, INRAE en a 3 côté DataCite). Retrait de `publishers.doi_prefix` (mono-valeur, redondant) effectué en Phase 1.

3. **Résolution paresseuse via `doi.org/ra` + endpoints RA**. Pas de bootstrap massif. Au fil des préfixes inconnus rencontrés dans le staging, la table se peuple.

4. **Structure à deux niveaux symétrique entre RAs** :

   | RA | Niveau 1 (préfixe nu identifie) | Niveau 2 (identifié par...) |
   |---|---|---|
   | Crossref | publisher (`api.crossref.org/prefixes/{p}.name`) | journal (premier segment post-slash, via `journals.doi_prefix` pattern) |
   | DataCite | provider (`/prefixes/{p}.relationships.providers`) | client (`/prefixes/{p}.relationships.clients`, 1-to-1 avec le préfixe) |

   - **Niveau 1 (publisher / provider)** stocké dans les colonnes `publisher_*` existantes. Côté DataCite, c'est le provider DataCite qui occupe ce slot — peut matcher un publisher Crossref existant (cas Classiques Garnier qui apparaît côté Crossref ET DataCite).
   - **Niveau 2 (client)** stocké dans des colonnes dédiées `client_name_raw` / `client_name_normalized` sur `doi_prefixes`, peuplées uniquement pour les rows DataCite. Côté Crossref, le niveau 2 (journal) reste géré par `journals.doi_prefix` au niveau publication, pas préfixe.

5. **Stockage des IDs registry-assignés en colonnes séparées et typées**. `crossref_member_id` (`integer`, peuplé uniquement si Crossref) et `datacite_client_symbol` (`text`, peuplé uniquement si DataCite). Choix retenu vs consolidation JSONB unique : typage préservé, indexabilité B-tree native, lisibilité SQL. Pas de scalabilité combinatoire à craindre puisque les autres RAs sont hors scope.

6. **DataCite intégré à `resolve_doi_prefixes`** au même titre que Crossref. Endpoint `api.datacite.org/prefixes/{p}?include=clients,providers`, 1 préfixe = 1 client validé sur 105/105 sur l'échantillon UCA (cf. spike Phase 0).

7. **DataCite ingérée par DOI, comme Crossref.** Le spike comparatif (`datacite-vs-natives-spike.md`) a montré que DataCite ≥ API native Zenodo sur les champs biblio : pas d'extracteur natif à écrire pour exploiter ces DOI. L'ingestion se fait en cross-import par DOI via `fetch_missing_doi --target datacite`, payload inséré en staging puis normalisé comme toute autre source.

8. **La résolution concept/version passe par DataCite, pas par l'API Zenodo.** Le versioning est un concept DataCite général (`relatedIdentifiers` : `IsVersionOf` / `HasVersion` / …), porté par tout DOI DataCite, pas seulement Zenodo. Une preuve de concept a mesuré un recouvrement de 100 % du chemin version→concept (`IsVersionOf`) contre la vérité terrain Zenodo (les `zenodo_concept_doi` déjà résolus). La résolution cesse donc d'être une phase dédiée tapant l'API Zenodo : elle devient un sous-produit de l'ingestion DataCite (les `relatedIdentifiers` arrivent dans le payload, peuplent `related_dois`, le concept se lit dans `IsVersionOf`).

### Schéma

`doi_prefixes` (mise à jour Phase 2) :

```sql
CREATE TABLE doi_prefixes (
    prefix text PRIMARY KEY,                    -- '10.1038', '10.5281', etc.
    ra text NOT NULL,                           -- 'Crossref', 'DataCite', 'mEDRA', 'unknown'
    publisher_id integer REFERENCES publishers(id) ON DELETE SET NULL,
    publisher_name_raw text,                    -- Crossref: api.crossref.org/.../name | DataCite: provider.name
    publisher_name_normalized text,             -- normalize_text(publisher_name_raw), pour re-match différé
    crossref_member_id integer,                 -- 'member' Crossref, nullable, peuplé uniquement si ra='Crossref'
    client_name_raw text,                       -- DataCite uniquement : client.name (Zenodo, NAKALA, INRAE, …)
    client_name_normalized text,                -- DataCite uniquement : normalize_text(client_name_raw)
    datacite_client_symbol text,                -- DataCite uniquement : client.symbol (ex. 'cern.zenodo', 'inist.inra'), stable au-delà des renommages
    fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_doi_prefixes_ra ON doi_prefixes (ra);
CREATE INDEX idx_doi_prefixes_publisher ON doi_prefixes (publisher_id) WHERE publisher_id IS NOT NULL;
CREATE INDEX idx_doi_prefixes_publisher_name_normalized
    ON doi_prefixes (publisher_name_normalized) WHERE publisher_id IS NULL;
CREATE INDEX idx_doi_prefixes_client_name_normalized
    ON doi_prefixes (client_name_normalized) WHERE client_name_normalized IS NOT NULL;
CREATE INDEX idx_doi_prefixes_datacite_client_symbol
    ON doi_prefixes (datacite_client_symbol) WHERE datacite_client_symbol IS NOT NULL;
```

`client_name_*` et `datacite_client_symbol` sont nullables et restent NULL pour les rows non-DataCite — pas d'enum strict, le `ra` qualifie la sémantique des colonnes. Choix `datacite_client_symbol` (colonne texte dédiée) plutôt qu'une consolidation JSONB avec `crossref_member_id` : typage préservé (`integer` vs `text`), indexabilité B-tree native, lisibilité SQL.

### Place dans le pipeline

Ordre dans `run_pipeline.py` (déjà en place depuis Phase 1) :

```
extract → cross_imports (fetch_missing_hal_id + fetch_missing_doi) → normalize → resolve_doi_prefixes → publications → …
```

`resolve_doi_prefixes` se lance **après normalize** : (1) `cross_imports` peut introduire de nouveaux DOIs en staging via les refetch HAL ; (2) `normalize` crée les publishers via `find_or_create_publisher`, donc le matching `publisher_name_normalized` au moment de résoudre les préfixes bénéficie des publishers fraîchement créés.

L'ingestion DataCite par DOI (Phase 3) s'ajoute comme cible de `fetch_missing_doi` dans `cross_imports`, au même titre que crossref.

## Phasage

### Phase 0 — Spike & validation ✓

- [x] Inventaire des préfixes en staging → distribution des RAs (Crossref 80.9 %, DataCite 13.4 %, unknown 2.6 %, autres 2.0 % sur 910 préfixes).
- [x] Sample ~70 DOIs DataCite stratifiés par doc_type, évaluation des champs (creators avec ORCID 41 %, affiliations 59 %, container 40 %, relatedIdentifiers 67 %, resourceTypeGeneral).
- [x] Volume CrossRef économisé par le filtre : ≈ 12 % d'appels (3 000 / 24 000) + élimination des stubs `not_found=TRUE` polluants.
- [x] Spike complémentaire `prefixes-datacite` : 105/105 préfixes DataCite résolus, **1 préfixe = 1 client**, 77 providers distincts (CNRS = 20 % via 2 IDs).
- [x] Spike comparatif Zenodo / INRAE (`datacite-vs-natives-spike.md` §1-2) : sur Zenodo, DataCite ≥ API native sur les champs biblio (pas d'extracteur natif à écrire) ; sur INRAE, hypothèse Dataverse invalidée (0/36), pas d'API native unique à comparer.
- [x] Validation résolution concept/version : recouvrement 100 % du chemin version→concept via `IsVersionOf`, contre vérité terrain Zenodo. Preuve de concept faite, artefacts non conservés.
- **Livrables** : `doi-prefixes-spike.md`, `datacite-vs-natives-spike.md` + oneshots associés.

### Phase 1 — `doi_prefixes` + filtre CrossRef + retrait `publishers.doi_prefix` ✓

- [x] Migration Alembic `0019_doi_prefixes` : `CREATE TABLE doi_prefixes` + index.
- [x] One-shot `seed_doi_prefixes.py` : seed initial (871 préfixes résolus + 711 mappings publisher).
- [x] Clients `doi.org/ra` + `api.crossref.org/prefixes/{prefix}` dans `infrastructure/sources/doi_prefixes/`.
- [x] Phase pipeline `resolve_doi_prefixes` : retry multi-DOI (N=3), résolution RA, mapping publisher Crossref, insert dans `doi_prefixes`. Préfixe non résolvable → pas d'insert (retry au run suivant).
- [x] Wiring dans `run_pipeline.py`, placé **après normalize**.
- [x] `get_cross_import_dois` : LEFT JOIN sur `doi_prefixes`, filtre `ra = 'Crossref' OR ra IS NULL` pour la cible crossref.
- [x] Adapter API/UI publishers : retrait du champ `doi_prefix` ; vue lecture seule des préfixes via JOIN.
- [x] Migration Alembic `drop_publishers_doi_prefix`.

### Phase 2 — DataCite dans `resolve_doi_prefixes` ✓

- [x] Migration Alembic `a4f7c1e8d2b6` : `ADD COLUMN client_name_raw, client_name_normalized, datacite_client_symbol` + index partiels.
- [x] Client `fetch_datacite_prefix(prefix) -> (provider_name, client_name, client_symbol) | None` dans `infrastructure/sources/doi_prefixes/clients.py` (parser JSON:API isolé pour testabilité).
- [x] Branche `ra='DataCite'` dans `resolve_doi_prefixes` : provider en `publisher_*` (mêmes règles de match/création que Crossref), client en colonnes dédiées. Au passage : `UnmatchedCrossrefPrefix` → `UnmatchedPrefix` (agnostique RA).
- [x] Tests unitaires (parser DataCite) + intégration (branche pipeline).
- Note : sur prod, les rows DataCite antérieures à cette phase ont `client_*` et `datacite_client_symbol = NULL` — rattrapage par re-seed ou re-run de `resolve_doi_prefixes`.

### Phase 3 — Source DataCite ingérée par DOI

Cross-import par DOI, calqué sur Crossref. Aucun extracteur natif, aucun sweep par affiliation.

- [x] `_TARGET_RA["datacite"] = "DataCite"` dans `infrastructure/sources/common.py` : un appel DataCite ne reçoit que des DOI DataCite (filtre RA déjà en place pour crossref). (f5b3b0c0)
- [x] Adapter `DataciteFetchMissingDoiAdapter` (`infrastructure/sources/datacite/fetch_missing_doi.py`), calqué sur `CrossrefFetchMissingDoiAdapter` : `GET api.datacite.org/dois/{doi}`, insert du payload en staging. 404 → stub `not_found` (DataCite est source native du DOI pour ses préfixes). (f5b3b0c0)
- [x] Wiring de la cible `datacite` dans `_make_fetch_missing_doi_adapter` + `run_pipeline.py`. (f5b3b0c0)
- [x] Enum SQL `source_type += 'datacite'` (migration Alembic), ajout aux constantes `domain/sources/`. (f5b3b0c0)
- [x] Position de DataCite dans `SOURCE_PRIORITY` : hypothèse de travail symétrique à Crossref (chaque RA fait autorité pour son périmètre, jamais en concurrence sur la même publi). (f5b3b0c0)
- [x] Normalizer DataCite (`application/pipeline/normalize/normalize_datacite.py` + ports + queries + CLI) : mapping vers `publications` / `source_publications` / `source_authorships`. (ce5a1abe)
- [x] Mapping `doc_type` DataCite : token brut (`resourceTypeGeneral` spécifique, fallback `resourceType` libre) mappé par `_SOURCE_MAPS["datacite"]`, seedé sur la distribution réelle du corpus. (ce5a1abe)
- [x] `relatedIdentifiers` de type DOI : `meta.related_identifiers` conserve la nature typée (`relationType`) ; `external_ids.related_dois` reçoit le sous-ensemble « œuvre à rapatrier » (versions / formes / parties / suppléments), citations exclues du pool cross-import. (ce5a1abe)
- **Livrable** : `source_publications` peuplée pour les DOI DataCite apportés par les autres sources, ingérées par le pipeline normal.

### Phase 4 — Résolution concept/version via DataCite

Débloquée par la validation concept/version (recouvrement 100 % du chemin version→concept via `IsVersionOf`). La résolution ne tape plus l'API Zenodo : c'est un **cas de la correction de DOI par cluster** (au même titre que l'unaire empile ses règles).

- [x] Le concept est dérivé d'un mapping `version_doi → concept_doi` (depuis `meta.related_identifiers` `IsVersionOf` des SP `datacite`) appliqué à **toutes** les SP partageant le DOI de version, toutes sources — convergence cross-SP par périmètre, sans cache. (6c5f9884)
- [x] La branche cluster gère désormais plusieurs cas : convergence version→concept (substitution) + divergence ouvrage/chapitre (nullage). `detect_erroneous_key_holders` → `resolve_cluster_doi_corrections`, `DistinctMergeCase` → `DoiClusterCase`. (6c5f9884)
- [x] Suppression de la phase `zenodo_doi`, de `resolve_zenodo_concept`, `correct_zenodo_concept`, `HttpZenodoResolver`, `domain/sources/zenodo.py` + ports/queries/CLI/tests. Migration de nettoyage de la clé obsolète `external_ids.zenodo_concept_doi`. (6c5f9884)
- [x] Auto-cicatrisation : une SP dont le concept n'est plus dérivable restaure son DOI brut (versions très récentes au graphe DataCite incomplet → rattrapées au run suivant). (6c5f9884)
- **Livrable** : concept/version résolu pour tout fournisseur DataCite (Zenodo, figshare, Dryad…), sans phase ni API dédiée. Transition : les substitutions déjà en base se re-dérivent via l'ingestion DataCite ; un run complet (cross-import datacite avant `metadata_correction`) les reconverge.

### Phase 5 — UI

- [x] Icône DataCite dans les **mêmes contextes que l'icône Crossref** (pas dans les tableaux de publications — c'est le lien DOI qui joue ce rôle).
- [ ] Endpoint admin (optionnel) pour visualiser la distribution par RA et auditer les préfixes `unknown` / `publisher_id IS NULL`.

## Questions ouvertes

1. **Politique de réinterrogation `ra='unknown'`** : ré-essai après N jours ou jamais ? Par défaut jamais, refetch manuel via flag CLI.

2. **Purge des `not_found=TRUE` côté CrossRef** post-filtre : les DOIs DataCite déjà marqués `not_found=TRUE` (legacy avant Phase 1) restent comme stubs. À garder ou à purger via one-shot ?

3. **Matching `publisher_name_raw` → `publishers` existant** : seuils et règles (exact normalized, fuzzy, manuel). Démarrage par exact-match sur `name_normalized`, fallback `publisher_id NULL` pour traitement admin manuel.

4. **Filtre `get_cross_import_dois("datacite")` et DOIs synthétiques** : arbitrage de l'exclusion `10.60692` (DOIs synthétiques OpenAlex) — laissé ouvert.

5. **DataCite *affiliation-driven* / *ORCID-driven*** — chantiers ultérieurs, hors scope ici. Le spike discovery par affiliation (`datacite-vs-natives-spike.md` §3) a montré que `creators.affiliation.name:"Université Clermont Auvergne"` retourne 2 298 publications dont 1 922 (84 %) absentes de la base locale (top apports : INRAE 860, Zenodo 457, Recherche Data Gouv 240). DataCite est donc exploitable affiliation-driven, mais cela ouvre des questions propres : full sweep périodique vs incrémental via `updated` ; `creators` seul vs union `creators + contributors` (2 298 vs ~2 500-2 800 hits) ; rejouer le spike sur la base de prod (le 84 % est mesuré sur la base locale, non représentative) ; architecture probablement partagée avec le volet Crossref affiliation-driven (`METIER_crossref.md` Phase 6). Acquis du chantier, pas de son périmètre.

6. **Facette « DOI » dans les filtres de listes** (crossref / datacite / other / none) — hors scope. À traiter quand DataCite sera ingérée et l'icône posée.

7. **Frontière avec `METIER_relations-publications`** : ce chantier livre le canal d'ingestion (`relatedIdentifiers` → `related_dois`). La modélisation des relations (table `publication_relations` vs JSONB, cardinalités, effet UI) reste dans l'autre fiche.

## Liens

- doi.org RA API : <https://www.doi.org/factsheets/DOIProxy.html#rest-api>
- CrossRef Prefixes API : <https://api.crossref.org/swagger-ui/index.html#/Prefixes>
- DataCite REST API : <https://support.datacite.org/docs/api>
- DataCite metadata schema : <https://schema.datacite.org/>
- Spike Phase 0-1 : `docs/chantiers/doi-prefixes-spike.md`
- Spike comparatif + affiliation-driven : `docs/chantiers/datacite-vs-natives-spike.md`
- Chantier jumeau publishers/journals : `docs/chantiers/METIER_publishers-journals.md`
- Chantier relations : `docs/chantiers/METIER_relations-publications.md`
- Chantier cousin Crossref (affiliation-driven) : `docs/chantiers/METIER_crossref.md` Phase 6
