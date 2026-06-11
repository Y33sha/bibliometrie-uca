# Chantier — Publications : matching par création⇒fusion + modélisation des identifiants

Commencé le 2026-06-10 - terminé le 2026-06-11

## Contexte

Le matching actuel (`match_or_create_publications`) est asymétrique :
- **Phase A** (per-document, in-périmètre) : `decide_publication_match` crée ou rattache via la cascade DOI → NNT → HAL_ID → PMID → titre/année ; `resolve_doi_conflict` arbitre les conflits de DOI (chapitre/ouvrage/titre).
- **Phase B** (bulk, hors-périmètre) : rattachement set-based des orphelins restants par DOI/NNT/hal_id/pmid, **sans** `resolve_doi_conflict`.

Problèmes :
- La règle de non-fusion (chapitre/ouvrage) ne tourne qu'en Phase A. La passe **bulk DOI rattache à l'aveugle** → fusions abusives (ouvrage + ses chapitres sous le DOI du livre). La corriger en SQL revient à **disperser la logique métier** (proxies `container_title`, types bruts par source) — code smell.
- Le rattachement orphelin **`source_publication` → publication est asymétrique** : un `source_publication` n'a ni `title_normalized` ni `doc_type` canonique, donc on ne peut pas y appliquer proprement `resolve_doi_conflict`.
- La contrainte `UNIQUE (lower(doi))` force un **match-à-la-création** pour le DOI, à rebours de l'uniformité visée.

**Pivot : création⇒fusion.** Chaque `source_publication` crée une publication ; des passes de **fusion pub↔pub** dédupliquent. Toute la logique de (non-)fusion vit alors à **un seul endroit** (`resolve_doi_conflict` + les clés), sur des publications qui portent `doc_type` + `title_normalized` des deux côtés — fini les proxies SQL et l'angle mort `source_publication`→pub.

## Décisions

- **Modèle création⇒fusion** : 1 publication par `source_publication` à la création (plus de gate), puis passes de **fusion pub↔pub** (clés : DOI, hal_id, nnt, pmid, titre/année), avec `resolve_doi_conflict` en arbitre (chapitre/ouvrage/titre) et `distinct_publications` comme **garde uniforme pub↔pub**.
- **Périmètre — pas de gate, marquage plutôt que suppression** : à la création, on ne filtre plus sur le périmètre. Les publications hors-UCA existent donc, mais sont marquées par un **flag `publications.in_perimeter`** (dérivé : ≥1 authorship in-périmètre) — ou exposées via une vue `perimeter_publications` — sur lequel les consommateurs filtrent. Suppression éventuelle **différée** (faible volume ; une publication sans authorship est invisible une fois les consommateurs filtrés). Aujourd'hui l'invariant « toute publication est UCA » est implicite (garanti par le gate) et ~10 consommateurs `FROM publications` n'ont aucun filtre périmètre — c'est ce qu'il faut reprendre. (Alternative écartée : créer puis **supprimer** les publications hors-UCA — destructif, ordre délicat, et re-création en boucle des `source_publication` orphelins.)
- **Contrainte `UNIQUE (lower(doi))` supprimée** → index simple. Le DOI devient une **clé de fusion** ; l'unicité « 1 publication = 1 DOI » est garantie par la passe de fusion (eventual), plus par la DB. Garder la contrainte = ré-introduire le match-à-la-création (l'asymétrie qu'on fuit).
- **Modélisation des identifiants** :
  - `publications.doi` = **DOI primaire, 1:1** (l'identifiant qui pointe vers la localisation faisant autorité). Primaire = top-level OpenAlex / premier `externalIds type=doi` ScanR — audit : éditeur **~97 %** (OpenAlex) / **~98 %** (ScanR). Les mésclassements `doc_type` (un doc publié typé `preprint` par OpenAlex) relèvent des **règles de correction** (doc-types), pas du choix de DOI.
  - **`external_ids.related_dois` (LIST)** = tous les **autres** DOI du record (preprint, dépôt, dataset, DOI de l'ouvrage hôte d'un chapitre, autre édition). **Jamais clé de fusion.** Matière pour **relations-publications** + `resolve_doi_prefixes`. Remplace l'actuel `source_doi` (même nature : un DOI présent dans la source, lié mais pas celui *du* document).
  - **DOI distincts = publications distinctes** ; le lien (publié ↔ preprint, ouvrage ↔ chapitres, édition ↔ édition) se modélise dans **relations-publications**.
  - `external_ids.hal_id` (liste, déjà en place), `pmid`/`nnt`/`pmcid`/`arxiv_id` scalaires (≈1:1).

## Phasage

### Phase 1 — Extraction de tous les DOI
- [x] Capter tous les DOI d'un record : primaire → `publications.doi`, le reste → `external_ids.related_dois` (OpenAlex : top-level + `location.id` `doi:` + URLs `doi.org` ; ScanR : `externalIds type=doi`, le `doiUrl` étant toujours redondant). HAL/crossref/wos/theses : mono-DOI par structure.
- [x] Les consommateurs de DOI itèrent sur tous les DOI (primaire + `related_dois`) : `resolve_doi_prefixes` (résolution préfixe → RA/éditeur) et les `cross_imports` par DOI (`get_cross_import_dois`). Mécanique : les `related_dois` d'un run sont consommés au run suivant (sortie de normalize), comme le tolère le pipeline convergent.

### Phase 2 — Schéma
- [x] Étendre la vue `v_active_publications` : scope doc_type **ET** in-perimeter (`EXISTS source_authorships.in_perimeter`) → définition unique d'« affleurant » (hors-périmètre = hors-scope, comme `peer_review`/`memoir`). Le périmètre se dérive, pas de colonne `in_perimeter` à entretenir. Les consommateurs pipeline qui joignent la vue (`build_authorships`, `persons_create`) en héritent. (migration ; à appliquer après le réimport des thèses)
- [x] Prérequis : rattacher les thèses au périmètre (l'établissement de soutenance UCA dans les adresses des authorships theses.fr).
- [x] Supprimer la contrainte `UNIQUE (lower(doi))` → index simple (migration + `tables.py`). Prérequis du retrait du gate : sans ça, deux source_publications à même DOI → violation. L'unicité « 1 DOI = 1 publication » devient garantie par la passe de fusion.
- Consolidation API **écartée** (examinée) : l'API filtre déjà le périmètre via `PUBLICATION_IS_IN_PERIMETER` (authorships **canoniques** in_perimeter, dans `filters.py`), notion distincte du périmètre **source** de la vue ; le `doc_type NOT IN` des requêtes API est le socle de scope uniforme (modes personne/labo/global), déjà DRY via `OUT_OF_SCOPE_DOC_TYPES_SQL`. Rien à consolider sans confondre les couches.

### Phase 3 — Logique de traitement
- [x] Cas de **distinction** (domaine pur) : `domain/publications/distinct_publications.py` — ouvrage vs chapitre, deux chapitres titres différents, thèse/mémoire vs article. Pas d'effet de bord (« juste détecter et marquer »). `resolve_doi_conflict` supprimé (plus de « conflit » de DOI sans la contrainte unique).
- [x] Passe applicative `mark_distinct_publications` : pour les paires partageant une clé, applique `detect_distinct_case` et peuple `distinct_publications`. Câblée avant les fusions (ordre create → distinct → merge).
- [x] Garde **« deux DOI non-nuls différents ⇒ pas de fusion »** dans `merge_publications` (`DistinctDoiError`, traitée en skip par `merge_publications_by_key`). Les cas « il faudrait quand même fusionner » = DOI erroné ou documents liés → traités plus tard.
- [x] Passes de fusion par **identifiant** : DOI / hal_id / nnt / pmid via `merge_publications_by_key`, gardées par `distinct_publications` (paires pré-marquées) **et** « DOI distincts ». hal_id/nnt existaient ; DOI + pmid ajoutées (la passe pmid corrige 85 doublons réels). Câblées en phase publications.
- [x] Fusion par **métadonnées** (thèse, proceedings) : `merge_pubs_by_metadata` — paires au même `title_normalized` + `pub_year`, critères réutilisés (compat auteur primary thèse, nombre d'auteurs proceedings). Câblée après les fusions par identifiant.
- [x] Création d'1 publication par `source_publication` (retrait du gate + matching + Phase B), `effective_metadata` à la création. La requête remonte tous les orphelins ; le dédoublonnage est délégué aux passes de fusion. Param `commit` sur les passes pour le helper de tests.
- [x] **Logique métier de dédup rapatriée dans `domain/publications/deduplication.py`** (`DeduplicationKey` + `MetadataDeduplicationCase` + `detect_metadata_merge_case` pure), importée par les passes (`merge_pubs_by_metadata` appelle la règle ; les passes par identifiant déclarent leur `DeduplicationKey`). Code mort retiré : `resolve_doi_conflict`, `decide_publication_match`, le module `metadata_deduplication_rules`, les finders inutilisés (`find_by_nnt`/`hal_id`/`pmid`, `find_thesis_by_title`, `find_proceedings_by_title_year`), les accesseurs DOI (`get_doi`/`set_doi`/`clear_doi`) + leurs tests. L'auto-fusion DOI au sein de `refresh_from_sources` (vestige de la contrainte UNIQUE) est retirée : le dédoublonnage DOI passe uniformément par `merge_pubs_by_doi` ; `find_by_doi` + `PubByDoi` supprimés en conséquence.

### Phase 4 — Consommateurs
- [x] Filtre périmètre sur les vues **globales** de publications (`publications/list`, `facets`, `stats/summary|journals|publishers`) — déjà en place via `PUBLICATION_IS_IN_PERIMETER`.
- [x] Catalogues **journals** et **publishers** : `pub_count`, EXISTS « a des publications », répartitions doc_type/oa, sujets-par-entité ne comptent plus que les publications in-perimeter + in-scope. Filtre paramétré par alias (`publication_in_perimeter(alias)`) car le publisher occupe déjà `p`.
- Lecture **hors-périmètre assumée** pour labos / personnes / adresses (pas de filtre).
- [ ] **Sujets** (`usage_count` + co-occurrences) à restreindre au périmètre — dans la **phase subjects du pipeline**, pas à la requête. Reporté à un chantier ultérieur (suivi hors fiche).

### Phase 5 — Migration / rerun
- [ ] Rerun complet du stock après bascule.

## Questions ouvertes

- **Ordre des passes de fusion** + idempotence (résolution des chaînes de redirection dans un batch — `merge_publications_by_key` le fait déjà pour nnt/hal_id).
- **Cycle de vie des publications hors-périmètre** : suppression différée ou non, à trancher après observation (volume, propreté).
- **`resolve_doi_conflict` N-aire** (ouvrage + N chapitres) + inscription des paires dans `distinct_publications`.
- Volume/perf de la création de masse puis fusion (faible au volume UCA, mais à mesurer).

## Liens

- [METIER_fusions-abusives-sources](../METIER_fusions-abusives-sources.md) — ce chantier **absorbe** son volet chapitres/ouvrage : la garde anti-fusion devient triviale et uniforme en pub↔pub (plus de bricolage SQL). Reste à ce chantier-là le critère thèse↔article (revue ⇔ dépôt-thèse) et le circuit d'override admin.
- [METIER_relations-publications](../METIER_relations-publications.md) — consomme `related_dois` (publié ↔ preprint ↔ dépôt, ouvrage ↔ chapitres, éditions).
- [METIER_doc-types](../METIER_doc-types.md) — les mésclassements preprint/dataset se règlent par règles de correction, pas par le choix de DOI.
- État actuel : [`match_or_create_publications.py`](../../../application/pipeline/publications/match_or_create_publications.py), [`deduplication.py`](../../../domain/publications/deduplication.py) (`resolve_doi_conflict`), [`merge.py`](../../../infrastructure/queries/pipeline/merge.py), [`resolve_doi_prefixes.py`](../../../application/pipeline/publishers_journals/resolve_doi_prefixes.py).
