# Chantier — DOI Registration Agencies & DataCite

Commencé le 2026-04-28

## Contexte

Un DOI est enregistré auprès d'une **Registration Agency** (RA) — chaque RA gère un sous-ensemble disjoint des préfixes DOI :

- **Crossref** : la majorité des articles de revue, chapitres d'ouvrage, thèses françaises (via ABES).
- **DataCite** : datasets, software, preprints, theses, repositories institutionnels (Zenodo, figshare, theses.fr, NAKALA, INRAE, etc.).
- **mEDRA / JaLC / Airiti / OP / KISTI / CNKI** : volumes négligeables côté UCA (< 1 % au total).

Aujourd'hui, `fetch_missing_doi --target crossref` interroge l'API CrossRef pour **tous** les DOI manquants en staging CrossRef, sans tenir compte de leur RA. Le spike Phase 0 a chiffré : sur 23 948 DOIs ciblés, 12 % sont en réalité DataCite (404 systématique, pollution `not_found=TRUE`) et 8 % sur des RAs non résolues.

Ce chantier traite deux faces du problème : **savoir** d'où vient chaque DOI, puis **exploiter** cette information pour économiser les appels CrossRef, enrichir le mapping prefix → éditeur, et ouvrir la voie à une ingestion DataCite.

Les préfixes DOI mappés aux `publishers` (et indirectement aux `journals`) serviront aussi au dédoublonnage des éditeurs/revues et à la détection des métadonnées incohérentes (DOI/`journal`, DOI/`doc_type`). Cf. chantier `METIER_publishers-journals.md`.

### Périmètre

**Inclus** :
- Table `doi_prefixes` (PK = préfixe DOI), peuplée paresseusement via `doi.org/ra` + `api.crossref.org/prefixes/{p}` + `api.datacite.org/prefixes/{p}`.
- Phase pipeline `resolve_doi_prefixes` qui gère les deux RAs principales (Crossref, DataCite) et stocke un mapping prefix → publisher.
- Filtrage de `get_cross_import_dois("crossref")` : skip les DOIs dont la RA ≠ `'Crossref'`.
- Pour DataCite, intégration à deux niveaux : provider (parent organisation, va dans `publishers`) + client (repository spécifique, colonnes dédiées sur `doi_prefixes`).
- Décision sur l'ingestion DataCite (ou des repositories natifs) conditionnée à un spike comparatif (Phase 3).
- Affichage UI conditionnel à la décision d'ingestion.

**Exclus** :
- Ingestion des autres RAs (mEDRA, JaLC, etc.). Volumes UCA négligeables.
- Discovery DataCite par affiliation. DataCite n'a pas d'index affiliation/ROR exploitable, on reste DOI-driven.
- Refetch périodique de la RA. Un préfixe ne change pas de RA en pratique (assignation permanente).
- Modification de `journals.doi_prefix` — concept différent (pattern de matching incluant un suffixe discriminant comme `10.1038/s41586` pour Nature), conservé tel quel.

## Décisions

### Architecturales actées

1. **Granularité = préfixe DOI, pas DOI individuel**. Un préfixe = un registrant = une RA permanente. Une table compacte côté préfixe (quelques centaines de rows pour le corpus UCA) est largement plus économe qu'un stockage per-DOI.

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

7. **Pas de table `clients` dédiée à ce stade**. Lien univoque depuis `doi_prefixes` uniquement vers le provider (via `publisher_id` → `publishers`). Le nom du client et le symbole DataCite sont dupliqués par préfixe pour les clients à plusieurs préfixes (INRAE×3, Heidelberg×2, etc.) — c'est exactement la même duplication que côté Crossref pour `publisher_name_*` quand un publisher détient plusieurs préfixes (Springer/Nature). Acceptable. Si un besoin de jointure univoque vers le client (analogue de la table `journals` côté Crossref pour le niveau 2) se présente plus tard, on ajoutera un `journal_id` / `client_id` à `doi_prefixes` à ce moment-là.

8. **Décision sur l'ingestion DataCite comme source = post-spike comparatif** (cf. Phase 3). Le spike Phase 0 a montré une couverture DataCite décente (41 % ORCID, 67 % `relatedIdentifiers`, 59 % affiliation textuelle), mais avec dispersion forte (101 clients distincts pour 105 préfixes). Avant d'investir dans l'ingestion, on compare DataCite vs APIs natives sur 2 repositories phares (Zenodo + INRAE) pour arbitrer : DataCite seul, extracteurs natifs, ou mix.

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

### Code (cible Phase 2)

- **`infrastructure/sources/doi_prefixes/clients.py`** : ajout d'un `fetch_datacite_prefix(prefix) -> (provider_name, client_name) | None`. Endpoint `https://api.datacite.org/prefixes/{p}?include=clients,providers`, parsing JSON:API, extraction de la première (et unique) relation client+provider via `included`.
- **`application/pipeline/resolve_doi_prefixes.py`** : pour `ra='DataCite'`, appel `fetch_datacite_prefix`, normalisation, matching `provider_name_normalized` contre `publishers.name_normalized` (mêmes règles que Crossref).
- **`infrastructure/sources/common.py::get_cross_import_dois`** : extension du filtre pour la cible `datacite` (cf. Phase 3, conditionnel).

### Place dans le pipeline

Ordre dans `run_pipeline.py` (déjà en place depuis Phase 1) :

```
extract → cross_imports (fetch_missing_hal_id + fetch_missing_doi) → normalize → resolve_doi_prefixes → publications → …
```

`resolve_doi_prefixes` se lance **après normalize** : (1) `cross_imports` peut introduire de nouveaux DOIs en staging via les refetch HAL ; (2) `normalize` crée les publishers via `find_or_create_publisher`, donc le matching `publisher_name_normalized` au moment de résoudre les préfixes bénéficie des publishers fraîchement créés.

## Phasage

### Phase 0 — Spike & validation

- [x] Inventaire des préfixes en staging (`SELECT split_part(doi, '/', 1) AS prefix, COUNT(*) FROM staging WHERE doi IS NOT NULL GROUP BY 1`).
- [x] Pour chaque préfixe distinct, requête `doi.org/ra` (un seul appel par préfixe via un DOI échantillon) → distribution des RAs (Crossref 80.9 %, DataCite 13.4 %, unknown 2.6 %, autres 2.0 % sur 910 préfixes).
- [x] Sample ~70 DOIs DataCite stratifiés par doc_type, requête API DataCite, évaluation des champs (creators avec ORCID 41 %, affiliations 59 %, container 40 %, relatedIdentifiers 67 %, resourceTypeGeneral).
- [x] Volume CrossRef économisé par le filtre : ≈ 12 % d'appels (3 000 / 24 000) + élimination des stubs `not_found=TRUE` polluants.
- [x] Spike complémentaire `prefixes-datacite` : 105/105 préfixes DataCite résolus via `api.datacite.org/prefixes/{p}`, **1 préfixe = 1 client**, 77 providers distincts (CNRS = 20 % via 2 IDs). Faisabilité de l'intégration dans `resolve_doi_prefixes` validée.
- **Livrable** : `docs/chantiers/doi-prefixes-spike.md` + `interfaces/cli/oneshot/doi_prefixes_spike.py`. **Phase 1 = GO. Phase 2 (résolveur DataCite) = GO. Phase 3 (ingestion) conditionnée à spike comparatif.**

### Phase 1 — `doi_prefixes` + filtre CrossRef + retrait `publishers.doi_prefix`

- [x] Migration Alembic `0019_doi_prefixes` : `CREATE TABLE doi_prefixes` + index.
- [x] One-shot `interfaces/cli/oneshot/seed_doi_prefixes.py` : seed initial depuis `docs/chantiers/doi-prefixes-spike-data/ra_cache.json` + `publisher_cache.json` (871 préfixes résolus + 711 mappings publisher).
- [x] Client `doi.org/ra` + client `api.crossref.org/prefixes/{prefix}` dans `infrastructure/sources/doi_prefixes/`.
- [x] Phase pipeline `resolve_doi_prefixes` : retry multi-DOI (N=3), résolution RA, mapping publisher pour Crossref, insert dans `doi_prefixes`. Préfixe non résolvable → pas d'insert (retry au run suivant).
- [x] Wiring dans `run_pipeline.py` (`--only resolve_doi_prefixes`, `--from resolve_doi_prefixes`), placé **après normalize**.
- [x] Modification `get_cross_import_dois` : LEFT JOIN sur `doi_prefixes`, filtre `ra = 'Crossref' OR ra IS NULL` pour la cible crossref.
- [x] Adapter API/UI publishers : retrait du champ `doi_prefix` côté Pydantic + admin Svelte ; vue lecture seule des préfixes via JOIN sur `doi_prefixes`.
- [x] Migration Alembic `drop_publishers_doi_prefix`.
- **Livrable** : appels CrossRef ciblés, `doi_prefixes` peuplée, mapping prefix → publisher many-to-one en place, pas encore de DataCite ingérée.

### Phase 2 — DataCite dans `resolve_doi_prefixes`

- [x] Migration Alembic `a4f7c1e8d2b6` : `ADD COLUMN client_name_raw, client_name_normalized, datacite_client_symbol` + index partiels.
- [x] Client `fetch_datacite_prefix(prefix) -> (provider_name, client_name, client_symbol) | None` dans `infrastructure/sources/doi_prefixes/clients.py` (parser JSON:API isolé pour testabilité).
- [x] Branche `ra='DataCite'` dans `application/pipeline/resolve_doi_prefixes.py` : provider en `publisher_*` (mêmes règles de match/création que Crossref), client en colonnes dédiées. Au passage : `UnmatchedCrossrefPrefix` → `UnmatchedPrefix` (agnostique RA), metrics `crossref_matched/crossref_created` → `publisher_matched/publisher_created`.
- [x] Tests unitaires sur le parser DataCite + tests d'intégration sur la branche pipeline.
- [x] Re-run de `--only resolve_doi_prefixes` (env de dev pour cette session). Note : sur prod, les rows DataCite existantes ont `client_*` et `datacite_client_symbol = NULL` — un rattrapage dédié sera nécessaire (one-shot ou extension passe 2) ; reporté ou couvert par un re-seed selon besoin.
- **Livrable** : mapping préfixe → provider + client en place pour les deux RAs, sans nouvelle source ingérée.

### Phase 3 — Décision ingestion (spike comparatif puis arbitrage)

- [ ] Spike comparatif sur 2 repositories phares : **Zenodo** (préfixe 10.5281, generaliste, volume probable) et **INRAE** (préfixes 10.14758 + 10.15454 + 10.17180, repository institutionnel français).
  - N DOIs UCA réels par repository, requête API DataCite vs API native du repository.
  - Grille de comparaison : creators + ORCID, affiliations, container, relatedIdentifiers, abstract, license, funder, doc_type.
  - Note de synthèse `docs/chantiers/datacite-vs-natives-spike.md` (ou enrichissement de la note existante).
- [ ] Arbitrage : DataCite seul / extracteurs natifs / mix par repository, en pesant aussi le nombre d'extracteurs à écrire pour couvrir les principaux repositories du corpus UCA.
- [ ] Implémentation conditionnée à la décision :
  - Si **DataCite seul** : extracteur DataCite (`infrastructure/sources/datacite/`), normalizer, mapping `doc_type` (cf. Phase 0 §`resourceTypeGeneral`), enum SQL `source_type` += `'datacite'`, ajout aux constantes `domain/sources.py`, filtre `get_cross_import_dois("datacite")` avec exclusion explicite du préfixe `10.60692` (DOIs synthétiques OpenAlex).
  - Si **extracteurs natifs** : un module `infrastructure/sources/<repo>/` par repository retenu, mêmes contraintes (ports, queries, mapping doc_type).
  - Si **mix** : DataCite par défaut + override natif sur les repositories où le delta justifie l'effort.
- **Livrable** : `source_publications` peuplée sur le périmètre DataCite-ingérable arbitré.

### Phase 4 — UI & cohérence finale (conditionnel à Phase 3)

- [ ] Icône dans la cellule « Sources » des tableaux publi (publications / theses / detail / personnes / labos).
- [ ] Facette source dans `SourceFilterToggle`.
- [ ] Endpoint admin (optionnel) pour visualiser la distribution par RA et auditer les préfixes `unknown` / `publisher_id IS NULL`.

## Questions ouvertes

1. **Politique de réinterrogation `ra='unknown'`** : ré-essai après N jours ou jamais ? Par défaut jamais, refetch manuel via flag CLI.

2. **Purge des `not_found=TRUE` côté CrossRef** post-filtre : les DOIs DataCite déjà marqués `not_found=TRUE` (legacy avant Phase 1) restent comme stubs. À garder ou à purger via one-shot ? Décision conditionnelle à Phase 3.

3. **Mapping doc_types DataCite** : à finaliser en Phase 3 (si ingestion DataCite retenue). Taxonomie `resourceTypeGeneral` documentée Phase 0 ; `Text` (45 % de l'échantillon) nécessite un fallback sur `resourceType` libre.

4. **Position de DataCite dans `SOURCE_PRIORITY`** : conditionnel à Phase 3. Hypothèse de travail : symétrique à Crossref (chaque RA fait autorité pour son périmètre, jamais en concurrence sur la même publi).

5. **Matching `publisher_name_raw` → `publishers` existant** : seuils et règles (exact normalized, fuzzy, manuel). Démarrage par exact-match sur `name_normalized`, fallback `publisher_id NULL` pour traitement admin manuel.

## Liens

- doi.org RA API : <https://www.doi.org/factsheets/DOIProxy.html#rest-api>
- CrossRef Prefixes API : <https://api.crossref.org/swagger-ui/index.html#/Prefixes>
- DataCite REST API : <https://support.datacite.org/docs/api>
- DataCite metadata schema : <https://schema.datacite.org/>
- Spike note : `docs/chantiers/doi-prefixes-spike.md`
- Chantier jumeau : `docs/chantiers/METIER_publishers-journals.md`
