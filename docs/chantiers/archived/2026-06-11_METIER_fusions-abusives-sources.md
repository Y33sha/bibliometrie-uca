# Chantier — Fusions abusives de documents distincts par les sources

Commencé le 2026-06-09 — clos le 2026-06-11.

## Clôture

Résolu pour l'essentiel par le pivot **création⇒fusion** ([2026-06-11_DATA_publications-creation-fusion](2026-06-11_DATA_publications-creation-fusion.md)), qui a absorbé le volet anti-fusion :

- **Ouvrage↔chapitres** et **thèse↔article (en paire)** : `detect_distinct_case` (`domain/publications/distinct_publications.py` — `OUVRAGE_VS_CHAPITRE`, `CHAPITRES_TITRES_DIFFERENTS`, `THESE_VS_ARTICLE`) + passe `mark_distinct_publications` ; les passes de fusion interrogent `distinct_publications`. L'angle mort **bulk DOI** (`bulk_link_orphans_by_doi`) a disparu — une publication par `source_publication`, le dédoublonnage passe par les fusions pub↔pub gardées.
- **`distinct_publications`** est devenue la garde **uniforme pub↔pub**, consultée par le pipeline (plus seulement l'API), et **repointée** du perdant vers le gagnant à la fusion (au lieu d'être supprimée) — une distinction survit donc à l'absorption d'une de ses publications.
- **`DUMAS (dumas.ccsd) ⇒ mémoire`** (l'aval) : règle dure URL-only rétablie (`DUMAS_URL_TO_MEMOIR`, inconditionnelle sur le `doc_type` brut), rattrapage du stock par `interfaces/cli/oneshot/refresh_publications_with_dumas_url.py`.

Différé / non bloquant :

- **Fusion abusive dans une seule `source_publication` OpenAlex** (cas b1/b2 ci-dessous) : **bénin**. La thèse (SP theses.fr / NNT) et l'article (SP DOI crossref…) sont moissonnés séparément et existent déjà comme deux publications ; la SP OpenAlex se rattache à l'une — l'article si le DOI éditeur est sa *primary location*, sinon la thèse par NNT (auquel cas le DOI article se retrouve sur deux publications, corrigeable a posteriori). Pas de distinction perdue.
- **Circuit d'override admin** (rendre une paire marquée re-fusionnable sur décision confirmée) : reporté à l'ouverture du chantier de déduplication admin manuelle.

## Contexte

Le matching cross-source rattache des `source_publications` orphelines à une publication canonique via `decide_publication_match` ([`match_or_create_publications.py`](../../../application/pipeline/publications/match_or_create_publications.py)) — cascade DOI → NNT → HAL_ID → titre/année (thèses, proceedings) — complétée par les passes bulk (Phase B : DOI, NNT, hal_id) et [`merge_pubs_by_hal_id.py`](../../../application/pipeline/publications/merge_pubs_by_hal_id.py).

Problème **inverse de la déduplication** : ici une source (OpenAlex le plus souvent) **agrège en une seule œuvre deux documents réellement distincts**, et notre matching propage cette fusion en une seule `publication` canonique.

### Cas observés

1. **Thèse ↔ article.** Une thèse (d'exercice ou doctorale) et l'article publié qui en est tiré — souvent même titre — finissent fusionnés : OpenAlex récupère le DOI de l'article et le pose sur l'entité qui porte aussi le dépôt de la thèse. Signe visible : une thèse qui porte un nom d'éditeur ou de revue. Ce sont deux documents (thèse > 100 p. ; article 10-20 p.). Ex. **pub 151542** (thèse d'exercice DUMAS + article).
2. **Chapitres distincts fusionnés par DOI commun** (le DOI est celui de l'ouvrage, partagé par tous ses chapitres). Ex. **pub 116652**.

### Ce qui résiste déjà / ce qui force la fusion

`resolve_doi_conflict` ([`domain/publications/deduplication.py`](../../../domain/publications/deduplication.py)) gère le conflit de DOI **dans le matching par document** : chapitre vs ouvrage → DOI retiré (pas de fusion) ; **deux chapitres aux titres différents → DOI invalidé des deux côtés, distinction préservée** ; sinon fusion.

Mais cette exception ne joue **que dans le chemin par document**. La passe **bulk** `bulk_link_orphans_by_doi` (Phase B, [`infrastructure/queries/pipeline/publications_match_or_create.py`](../../../infrastructure/queries/pipeline/publications_match_or_create.py)) rattache tout orphelin par **égalité de DOI brute** (`COALESCE(external_ids->>'zenodo_concept_doi', doi) = p.doi`), **sans** rejouer `resolve_doi_conflict` — donc sans l'exception chapitre/ouvrage/titre. C'est elle qui force ouvrage + chapitres sous une même publication via le DOI partagé du livre (vérifié sur 116652 : 3 enregistrements HAL `OUV`/`COUV` portant tous `10.4000/15s4x`).

### État de `distinct_publications`

Table de **paires symétriques** (`pub_id_a < pub_id_b`). `mark_distinct(a, b)` (idempotent) est posée par **action admin manuelle** depuis la revue des doublons. Aujourd'hui elle est consultée **uniquement par l'API** pour **exclure une paire des suggestions de doublons** ; le **pipeline ne la consulte jamais** (matching, merge bulk, `merge_pubs_by_hal_id`), et `merge_into` **supprime** les paires impliquant la publication fusionnée.

La garde est **« soft » par choix** : elle doit pouvoir être **outrepassée par une action admin** (avec confirmation). On veut donc une garde **dure contre la fusion automatique** (pipeline) mais **franchissable par décision humaine confirmée**. Aujourd'hui il n'existe **aucun circuit** pour cet override (une paire marquée distincte disparaît des suggestions de fusion) — à traiter plus tard.

### Conséquence aval

Tant que ces fusions ne sont pas défaites, la règle **`DUMAS (dumas.ccsd) => mémoire`** (url-only) ne peut pas s'appliquer proprement : elle forcerait un `doc_type` unique sur une entité qui mêle deux documents. Cette règle est donc **bloquée en amont par ce chantier** (cf. [METIER_doc-types](../METIER_doc-types.md)).

## Décisions

- **Deux familles, deux approches** :
  - **Ouvrage ↔ chapitres (OUV/COUV)** : la règle existe déjà (`resolve_doi_conflict`), seulement défaite par la passe bulk DOI → correctif **immédiat**, pas d'audit.
  - **Thèse ↔ article** : critère à découvrir → **maintenance-first** (audit + réparation par scripts, méthode empirique, risque réversible) avant toute intégration pipeline. Scripts dans `interfaces/cli/maintenance/`.
- **Critère absolu de non-fusion** (thèse↔article) : un côté revue (DOI de revue), l'autre **DUMAS / TEL / theses.fr** → documents nécessairement distincts.
- **❌ Pondérer les sources contre OpenAlex** : inopérant quand OpenAlex est la seule source.
- **Deux leviers de garde, complémentaires** :
  - `bulk_link_orphans_by_doi` applique l'**exception** chapitre/ouvrage/titre — la fuite OUV/COUV est un SP orphelin rattaché à une pub par DOI brut (pas une paire pub↔pub, donc `distinct_publications` ne la couvre pas).
  - `distinct_publications` = garde **pub↔pub** (`merge_pubs_*`, `merge_into`) : `resolve_doi_conflict` y inscrit la paire quand il scinde, ces passes l'interrogent. Reste **franchissable par l'admin** (cf. Contexte).

## Phasage

### 1. Ouvrage ↔ chapitres — garde immédiate (règle connue)

- Exception chapitre/ouvrage/titre dans `bulk_link_orphans_by_doi` : ne pas rattacher un SP `book_chapter` à une pub `book`, ni à une pub chapitre de titre différent.
- `resolve_doi_conflict` (chemin per-doc) inscrit la paire dans `distinct_publications` quand il scinde ; `merge_pubs_*` et `merge_into` l'interrogent (et cessent de l'effacer).
- Oneshot : re-split des OUV/COUV déjà fusionnés (≈55, cf. audit) + inscription des paires.

### 2. Thèse ↔ article — maintenance-first (critère à découvrir)

- Script d'audit (sans écriture) : critère revue ⇔ dépôt-thèse, affiné sur cas réels.
- Script de réparation : créer la 2ᵉ publication, répartir les `source_publications`, reconstruire les deux canoniques (`refresh_from_sources`), `mark_distinct`. Idempotent.
- Itérer audit ↔ réparation ; intégration à la création (cas b1) différée si justifiée.

### 3. Aval — `DUMAS => mémoire`

Une fois les fusions défaites (cf. [METIER_doc-types](../METIER_doc-types.md)).

### Audit initial (2026-06-09)

Premier passage exploratoire (lecture seule, base de prod) — sert à figer les règles avant d'écrire le script :

- **Signal A — revue (`journal_id`) + URL dépôt-thèse** (`dumas.ccsd`/`theses.fr`/`tel.archives`/`theses.hal`) : **43 publications**. Net (= critère absolu thèse↔article) : 29 `article`, 8 `thesis`, 4 `review`, 2 autres. Ex. 7248 (thèse d'exercice + article).
- **Signal B — titres HAL divergents** (≥2 `source_publications` HAL, titres distincts après `normalize_text`) : **232 brut, trop bruité** — dominé par versions FR/EN d'un même travail + variantes de titre (« front cover… », « compte rendu de lecture de… »). **Restreint à `doc_type ∈ {book, book_chapter}` → 55 publications, net** : ouvrage + ses chapitres fusionnés sur le DOI du livre (ex. 116652 : HAL `OUV` + 2 `COUV` sous `10.4000/15s4x`). Discriminant le plus sûr : une même publication portant à la fois des enregistrements HAL `OUV` et `COUV`.
- **Périmètre total ≈ 98** fausses fusions probables (43 + 55), hors résiduel non détectable.
- Enseignement : « titres ≠ sous un DOI » seul est inexploitable (FR/EN) ; c'est la restriction `book`/`COUV` qui rend la règle B utilisable. Règle A directement exploitable.

### Cas à la création (référence — détection en pipeline, différée)

- **(a) Faux doublon HAL d'abord** (même DOI, chapitres différents) : la distinction est déjà opérée par `resolve_doi_conflict` → y ajouter `mark_distinct`. Quand l'OpenAlex arrive ensuite (même DOI), empêcher la passe bulk DOI de re-fusionner (garde en place). Miroir thèse-first : thèse (HAL/theses.fr/DUMAS) d'abord, puis OpenAlex article — même forme, discriminant = le critère absolu.
- **(b1) OpenAlex d'abord, avec discriminant** (locations : revue + dépôt-thèse) : créer 2 publications, rattacher l'OpenAlex à la publication de sa `primary_location`, marquer distinct.
- **(b2) OpenAlex d'abord, sans discriminant** (chapitres, hal-ids distincts, même DOI) : une seule publication créée ; au traitement des `source_publications` HAL, refuser le co-matching → nouvelle publication + garde. Cas le plus complexe (différé, dépendant de l'ordre d'arrivée).

## Questions ouvertes

- **Circuit d'override admin** : rendre une paire marquée re-fusionnable sur décision confirmée, alors qu'elle est aujourd'hui masquée des suggestions. Mécanisme à définir.
- **Réparation** : répartir proprement `source_publications` **et** authorships entre les deux publications — le vrai risque du chantier, à piloter cas par cas avant tout automatisme.
- **Critère sur une `source_publication` OpenAlex unique** : le lire via ses *locations* (présence conjointe d'une location revue + une location dépôt-thèse) ?
- **Résiduel non-corrigeable** : OpenAlex fusionne deux docs sans aucun discriminant et aucune source HAL/theses.fr ne vient forcer la séparation → indétectable, reste fusionné.
- **Fusion N-aire (> 2 docs)** : ouvrage à N chapitres, ou thèse + article + preprint. Le modèle par paires tient mais l'enregistrement doit généraliser (marquer chaque nouveau distinct des précédents).
- **(b1) Métadonnées de la 2ᵉ publication** : stub depuis la *secondary location* OpenAlex, ou laissée à la vraie source-thèse à venir (le second choix ne peut pas poser de garde paire→paire tant que la 2ᵉ publication n'existe pas).
- **Create-then-merge vs passes orphelins** (hors scope, à évaluer) : créer une pub par `source_publication` puis fusionner rendrait `distinct_publications` une garde **uniforme** pub↔pub (plus d'angle mort SP→pub, plus besoin de dupliquer l'exception dans la passe bulk). Mais ça créerait les pubs hors-périmètre que le gate `in_perimeter` évite → cycle de vie à gérer. Restructuration du pipeline, pas un détour.

## Liens

- [METIER_doc-types](../METIER_doc-types.md) — la règle `DUMAS => mémoire` dépend de ce chantier ; reste ouverte ensuite la distinction mémoire / thèse d'exercice (que DUMAS lui-même ne fait pas : la thèse d'exercice y est typée mémoire), pour l'instant « mémoire » pour tout.
- [METIER_authorships-cross-source-matching](../METIER_authorships-cross-source-matching.md) — problème connexe mais inverse (rattacher les authorships d'un *même* document).
- État actuel : [`domain/publications/deduplication.py`](../../../domain/publications/deduplication.py) (`resolve_doi_conflict`), [`application/pipeline/publications/match_or_create_publications.py`](../../../application/pipeline/publications/match_or_create_publications.py) (`decide_publication_match` + Phase B), [`merge_pubs_by_hal_id.py`](../../../application/pipeline/publications/merge_pubs_by_hal_id.py), [`application/publications.py`](../../../application/publications.py) (`mark_distinct`, `merge_into`).
