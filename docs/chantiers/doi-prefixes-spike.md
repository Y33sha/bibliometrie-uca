# Spike — DOI Registration Agencies & DataCite (Phase 0)

Note de synthèse du spike `interfaces/cli/oneshot/doi_prefixes_spike.py`. Données brutes dans `docs/chantiers/doi-prefixes-spike-data/`.

## Distribution des Registration Agencies

Sur 910 préfixes DOI distincts résolus via `doi.org/ra` :

| RA | Préfixes | Part |
|---|---:|---:|
| Crossref | 736 | 80.9 % |
| DataCite | 122 | 13.4 % |
| unknown | 24 | 2.6 % |
| mEDRA | 18 | 2.0 % |
| JaLC + KISTI + Airiti + OP | 10 | 1.1 % |

Conformité avec l'hypothèse de cadrage : Crossref ultra-majoritaire, DataCite second avec une part significative, autres RAs négligeables.

## Impact volumétrique du filtre Crossref

Décompte des DOI staging par source × RA :

| RA | crossref | hal | openalex | scanr | theses | wos |
|---|---:|---:|---:|---:|---:|---:|
| Crossref | 18 970 | 45 375 | 42 811 | 53 831 | 1 586 | 18 637 |
| DataCite | **2 921** | 1 625 | 6 185 | 1 | 0 | 10 |
| unknown | 1 770 | 5 180 | 5 395 | 6 125 | 0 | 2 504 |
| mEDRA + autres | 17 | 189 | 38 | 129 | 0 | 22 |
| non résolu | 270 | 1 031 | 966 | 1 045 | 0 | 125 |
| **TOTAL** | **23 948** | 53 400 | 55 395 | 61 131 | 1 586 | 21 298 |

**Sur la colonne `crossref` (les 23 948 DOI sur lesquels `fetch_missing_doi --target crossref` tape aujourd'hui) :**

- 18 970 (79.2 %) sont effectivement Crossref → appel utile.
- 2 921 (12.2 %) sont **DataCite** → 404 systématique aujourd'hui, calls inutiles, pollution `not_found=TRUE`.
- 17 sont sur des RAs non couvertes (mEDRA, JaLC, etc.) → 404 systématique, marginal.
- 2 040 (8.5 %) sont `unknown` ou non résolus → best-effort, on garde dans la requête (filtre `ra IS NULL OR ra='Crossref'`).

**Économie attendue du filtre : 12 % de calls Crossref évités** (≈ 3 000 sur 24 000), et surtout **disparition de 3 000 stubs `not_found=TRUE`** qui aujourd'hui polluent staging et faussent les stats.

## Couverture canonique des publications par RA

Décompte des publications canoniques par RA × `doc_type` actuel en base :

| RA | TOTAL | article | thesis | book | chapter | proceedings | report | preprint | dataset | software | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Crossref | 22 068 | 14 715 | 1 564 | 65 | 794 | 626 | 626 | 607 | 52 | 0 | 986 |
| **DataCite** | **2 581** | 861 | 3 | 44 | 122 | 61 | 21 | 8 | 1 | 2 | 626 |
| unknown | 2 672 | 1 658 | 3 | 36 | 691 | 7 | 0 | 1 | 3 | 0 | 50 |
| mEDRA + autres | 50 | 38 | 0 | 0 | 2 | 3 | 3 | 0 | 0 | 0 | 3 |

**2 581 publications canoniques** sont sur préfixes DataCite. C'est le périmètre potentiel d'ingestion DataCite.

## Cohérence `doc_type` × RA

### Préfixes DataCite typés `article` (probablement à reclasser)

67 préfixes concernés. Top du suspect :

| Préfixe | Publisher | doc_type actuel | n | Lecture |
|---|---|---|---:|---|
| 10.60692 | OpenAlex | article | 325 | Preprints synthétiques générés par OpenAlex pour les publis sans DOI éditeur. Pas de métadonnées propres. |
| 10.6084 | figshare | article | 158 | Dépôt figshare — supplements, posters, datasets. Pas des articles. |
| 10.5281 | Zenodo | article | 94 | Dépôt Zenodo — datasets, software, preprints. Pas des articles. |
| 10.17180 | (à creuser) | article | 46 | — |
| 10.48611 | Classiques Garnier | article | 44 | Éditeur français. À ingérer ; sont effectivement des articles (resourceType="JournalArticle"). |

Conclusion : la majorité des "articles DataCite" sont en réalité des datasets / preprints / supplements mal catégorisés à la normalisation. L'ingestion DataCite + le re-mapping `doc_type` à partir de `resourceTypeGeneral` corrigera mécaniquement ces cas.

### Préfixes Crossref typés `thesis`

10.70675 (1 558 cas) = préfixe ABES (Agence Bibliographique de l'Enseignement Supérieur). Les thèses françaises sont enregistrées via Crossref par l'ABES — comportement attendu, **pas un faux positif**.

Les 5 autres préfixes Crossref taggés `thesis` ont 1-2 cas chacun, marginaux.

## Format DataCite

Échantillon de 71 DOI stratifiés par `doc_type_in_db`. Retours :

- 70/71 répondent en 200, 1 en 404. **Couverture API : bonne**.
- Pas de rate-limit problématique observé.

### `resourceTypeGeneral` distribution

| Type | n | Lecture |
|---|---:|---|
| Text | 32 | Type générique. Necessite de fallback sur le champ libre `resourceType` (« Article scientifique », « Preprint », …). |
| Dataset | 6 | Direct → `dataset`. |
| Preprint | 6 | Direct → `preprint`. |
| ConferencePaper | 5 | Direct → `conference_paper`. |
| Report | 4 | Direct → `report`. |
| Dissertation | 3 | Direct → `thesis`. |
| JournalArticle | 3 | Direct → `article`. |
| Software | 3 | Direct → `software`. |
| Collection / Audiovisual / Book / Image / Poster / StudyRegistration | 1-2 chacun | Direct → mapping naturel ou `other`. |
| (missing) | 1 | Fallback `other`. |

**Mapping doc_type DataCite : faisable**, mais la dominance du type générique « Text » (45 % de l'échantillon) impose un second niveau de mapping sur le champ libre `resourceType`. Pas bloquant, juste à coder soigneusement.

### Couverture des champs utiles

Sur les 70 records valides :

- **ORCID** : 29 records (41 %) ont au moins un creator avec un identifiant ORCID. **Signal article-level fiable** (comme Crossref).
- **Affiliation textuelle** : 41 records (59 %) ont au moins un creator avec une affiliation texte renseignée. Utile à la résolution `addresses → structures` mais qualité variable.
- **Container** : 28 records (40 %) ont un `container` (journal pour articles, repository pour datasets).
- **Publisher** : 100 % ont un publisher déclaré.
- **relatedIdentifiers** : 47 records (67 %) ont des `relatedIdentifiers` → bonus pour le chaînage preprint/version/dataset.

### Publishers DataCite les plus présents

Zenodo (12), Classiques Garnier (7), arXiv (6), Academic Journal of Civil Engineering (4), OpenAlex (4), Schloss Dagstuhl (4), figshare (4), Recherche Data Gouv, Inria, INRAE, etc.

Mix attendu pour un corpus universitaire français : dépôts institutionnels nationaux + grandes archives ouvertes + quelques éditeurs spécialisés.

## Décisions

### Phase 1 — filtre Crossref + retrait `publishers.doi_prefix` : **GO**

Gains tangibles, coût modéré (table + migration), pas de risque. Économie de 12 % d'appels Crossref + suppression des stubs `not_found=TRUE` polluants.

### Phase 2 — ingestion DataCite : **GO**, mais avec une nuance

Le périmètre métier mérite l'investissement (2 581 publications canoniques, 41 % d'ORCID, 67 % de `relatedIdentifiers`, mapping `doc_type` faisable). Apport spécifique attendu :

- **Datasets / software / preprints** non couverts ailleurs (ou mal couverts).
- **ORCID article-level** sur des publications qui en manquent côté OpenAlex/HAL.
- **`relatedIdentifiers`** pour le chaînage preprint ↔ version éditeur (cf. chantier `relations entre publications` ouvert dans TODO.md).

**Nuance** : le préfixe **10.60692 (OpenAlex « generated DOIs »)** est à **exclure de l'ingestion DataCite**. Ce sont des DOIs synthétiques que OpenAlex crée pour ses propres publis sans DOI éditeur — les métadonnées DataCite associées sont vides ou strictement redondantes avec ce qu'OpenAlex nous a déjà fourni. À filtrer côté `get_cross_import_dois('datacite')` ou à la normalisation.

Aujourd'hui ce préfixe représente 325 cas typés `article` en BDD — non négligeable, ils doivent être reclassés en `preprint` ou `other`, mais ça se fait depuis OpenAlex (réinterprétation de `primary_location`), pas via DataCite.

### Politique `unknown` / non résolu

Sur 24 préfixes `unknown` (RAs hors les 8 connues) et 270 DOI non résolus en staging crossref, on garde la sémantique défensive : `WHERE ra = 'Crossref' OR ra IS NULL` au filtre. Un préfixe nouveau non encore résolu est traité comme Crossref par défaut, quitte à essuyer un 404 si finalement il est ailleurs.

## Suite

→ Phase 1 du chantier `METIER_doi-ra-datacite` : table `doi_prefixes`, migration, client doi.org/ra, filtre `get_cross_import_dois`, retrait `publishers.doi_prefix`.

→ Phase 2 conditionnée à Phase 1 validée en prod : extracteur DataCite, normalizer, mapping `doc_type`, exclusion explicite du préfixe 10.60692.
