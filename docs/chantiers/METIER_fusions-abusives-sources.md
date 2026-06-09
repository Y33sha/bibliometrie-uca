# Chantier — Fusions abusives de documents distincts par les sources

## Contexte

Le matching cross-source rattache des `source_publications` orphelines à une publication canonique via `decide_publication_match` ([`match_or_create_publications.py`](../../application/pipeline/publications/match_or_create_publications.py)) — cascade DOI → NNT → HAL_ID → titre/année (thèses, proceedings) — complétée par les passes bulk (Phase B : DOI, NNT, hal_id) et [`merge_pubs_by_hal_id.py`](../../application/pipeline/publications/merge_pubs_by_hal_id.py).

Problème **inverse de la déduplication** : ici une source (OpenAlex le plus souvent) **agrège en une seule œuvre deux documents réellement distincts**, et notre matching propage cette fusion en une seule `publication` canonique.

### Cas observés

1. **Thèse ↔ article.** Une thèse (d'exercice ou doctorale) et l'article publié qui en est tiré — souvent même titre — finissent fusionnés : OpenAlex récupère le DOI de l'article et le pose sur l'entité qui porte aussi le dépôt de la thèse. Signe visible : une thèse qui porte un nom d'éditeur ou de revue. Ce sont deux documents (thèse > 100 p. ; article 10-20 p.). Ex. **pub 151542** (thèse d'exercice DUMAS + article).
2. **Chapitres distincts fusionnés par DOI commun** (le DOI est celui de l'ouvrage, partagé par tous ses chapitres). Ex. **pub 116652**.

### Ce qui résiste déjà / ce qui force la fusion

`resolve_doi_conflict` ([`domain/publications/deduplication.py`](../../domain/publications/deduplication.py)) gère le conflit de DOI **dans le matching par document** : chapitre vs ouvrage → DOI retiré (pas de fusion) ; **deux chapitres aux titres différents → DOI invalidé des deux côtés, distinction préservée** ; sinon fusion.

Mais cette exception ne joue **que dans le chemin par document**. La passe **bulk** `bulk_link_orphans_by_doi` (Phase B, [`infrastructure/queries/pipeline/publications_match_or_create.py`](../../infrastructure/queries/pipeline/publications_match_or_create.py)) rattache tout orphelin par **égalité de DOI brute** (`COALESCE(external_ids->>'zenodo_concept_doi', doi) = p.doi`), **sans** rejouer `resolve_doi_conflict` — donc sans l'exception chapitre/ouvrage/titre. C'est elle qui force ouvrage + chapitres sous une même publication via le DOI partagé du livre (vérifié sur 116652 : 3 enregistrements HAL `OUV`/`COUV` portant tous `10.4000/15s4x`).

### État de `distinct_publications`

Table de **paires symétriques** (`pub_id_a < pub_id_b`). `mark_distinct(a, b)` (idempotent) est posée par **action admin manuelle** depuis la revue des doublons. Aujourd'hui elle est consultée **uniquement par l'API** pour **exclure une paire des suggestions de doublons** ; le **pipeline ne la consulte jamais** (matching, merge bulk, `merge_pubs_by_hal_id`), et `merge_into` **supprime** les paires impliquant la publication fusionnée.

La garde est **« soft » par choix** : elle doit pouvoir être **outrepassée par une action admin** (avec confirmation). On veut donc une garde **dure contre la fusion automatique** (pipeline) mais **franchissable par décision humaine confirmée**. Aujourd'hui il n'existe **aucun circuit** pour cet override (une paire marquée distincte disparaît des suggestions de fusion) — à traiter plus tard.

### Conséquence aval

Tant que ces fusions ne sont pas défaites, la règle **`DUMAS (dumas.ccsd) => mémoire`** (url-only) ne peut pas s'appliquer proprement : elle forcerait un `doc_type` unique sur une entité qui mêle deux documents. Cette règle est donc **bloquée en amont par ce chantier** (cf. [METIER_doc-types](METIER_doc-types.md)).

## Décisions

- **Approche maintenance-first.** On commence par des **scripts de maintenance** (audit + réparation), pas par une modification du pipeline. On découvre les règles sur cas réels (méthode empirique) et on garde le risque réversible (un script se rejoue ; une régression de pipeline non). Les scripts vivent dans `interfaces/cli/maintenance/`.
- **Critère absolu de non-fusion** : un côté sur une revue (DOI de revue) **et** l'autre sur **DUMAS, TEL ou theses.fr** → documents nécessairement distincts.
- **Intégration pipeline (détection à la création) différée** jusqu'à des règles éprouvées ; peut rester hors pipeline si les scripts de maintenance suffisent.

## Phasage

1. **Script d'audit** — lister les fausses fusions probables. Signaux : DOI de revue + URL dumas/TEL/theses.fr sur la même publication ; titres différents sous un même DOI ; thèse portant un nom de revue/éditeur. Sortie = paires candidates + signal, **sans écriture**. C'est là qu'on découvre et affine les règles.
2. **Script de réparation** — pour une paire validée : créer la 2ᵉ publication, répartir les `source_publications` selon le critère, reconstruire les deux canoniques via `refresh_from_sources`, puis `mark_distinct`. Idempotent, rejouable. (`mark_distinct` et `merge_into` existent déjà.)
3. **Itérer 1 ↔ 2** jusqu'à des règles stables et un taux de faux positifs acceptable.
4. **Garde dure** (petite modif pipeline) — refuser la fusion d'une paire enregistrée : `WHERE NOT EXISTS (distinct_publications)` dans les requêtes de merge bulk + garde dans `merge_pubs_by_hal_id` et `merge_into` (qui aujourd'hui efface la garde). Conservatrice : ne fait que **refuser** des fusions marquées, n'invente aucune séparation. Doit rester franchissable par l'admin (cf. circuit d'override, plus bas).
5. **(Différé) Détection à la création** dans le pipeline — cas b1/b2 ci-dessous, une fois les règles éprouvées.
6. **Aval** : règle `DUMAS => mémoire` (cf. [METIER_doc-types](METIER_doc-types.md)).

### Audit initial (2026-06-09)

Premier passage exploratoire (lecture seule, base de prod) — sert à figer les règles avant d'écrire le script :

- **Signal A — revue (`journal_id`) + URL dépôt-thèse** (`dumas.ccsd`/`theses.fr`/`tel.archives`/`theses.hal`) : **43 publications**. Net (= critère absolu thèse↔article) : 29 `article`, 8 `thesis`, 4 `review`, 2 autres. Ex. 7248 (thèse d'exercice + article).
- **Signal B — titres HAL divergents** (≥2 `source_publications` HAL, titres distincts après `normalize_text`) : **232 brut, trop bruité** — dominé par versions FR/EN d'un même travail + variantes de titre (« front cover… », « compte rendu de lecture de… »). **Restreint à `doc_type ∈ {book, book_chapter}` → 55 publications, net** : ouvrage + ses chapitres fusionnés sur le DOI du livre (ex. 116652 : HAL `OUV` + 2 `COUV` sous `10.4000/15s4x`). Discriminant le plus sûr : une même publication portant à la fois des enregistrements HAL `OUV` et `COUV`.
- **Périmètre total ≈ 98** fausses fusions probables (43 + 55), hors résiduel non détectable.
- Enseignement : « titres ≠ sous un DOI » seul est inexploitable (FR/EN) ; c'est la restriction `book`/`COUV` qui rend la règle B utilisable. Règle A directement exploitable.

### Cas à la création (référence pour la phase 5)

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

## Liens

- [METIER_doc-types](METIER_doc-types.md) — la règle `DUMAS => mémoire` dépend de ce chantier ; reste ouverte ensuite la distinction mémoire / thèse d'exercice (que DUMAS lui-même ne fait pas : la thèse d'exercice y est typée mémoire), pour l'instant « mémoire » pour tout.
- [METIER_authorships-cross-source-matching](METIER_authorships-cross-source-matching.md) — problème connexe mais inverse (rattacher les authorships d'un *même* document).
- État actuel : [`domain/publications/deduplication.py`](../../domain/publications/deduplication.py) (`resolve_doi_conflict`), [`application/pipeline/publications/match_or_create_publications.py`](../../application/pipeline/publications/match_or_create_publications.py) (`decide_publication_match` + Phase B), [`merge_pubs_by_hal_id.py`](../../application/pipeline/publications/merge_pubs_by_hal_id.py), [`application/publications.py`](../../application/publications.py) (`mark_distinct`, `merge_into`).
