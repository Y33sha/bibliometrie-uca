# Chantier — Règles métier dans `domain/` : suppléments, doc_type suspects

Démarré le 2026-05-05.

## État

- **Phase 0** (inventaire) : ✅ terminée. L'inventaire a été nettoyé puis
  supprimé une fois ses items soit migrés, soit dispatchés vers les
  fiches dédiées ci-dessous.
- **Phase 1** (relocations sans changement de comportement) : ✅ terminée.
  Les helpers déjà identifiés ont été migrés au fil de l'eau dans
  `domain/sources/{openalex,scanr,theses,wos,hal,crossref}.py`,
  `domain/persons/{identifiers,creation,matching,merge,source_ids}.py`,
  `domain/publications/{dedup,scope}.py`, `domain/dates.py`.
- **Phase 2** (nouvelles règles « suspects » — figshare / Zenodo /
  DataCite + suppléments) : ⏳ ce chantier — c'est ce qui reste à
  faire ici.
- **Phase 3** (cascades de matching publications + cascade de matching
  personnes) : → fiches dédiées
  [`dedup-fusion-publications.md`](dedup-fusion-publications.md) et
  [`decide-person-match.md`](decide-person-match.md). Refactors
  structurels avec dimension métier (changement de logique), à
  démarrer en sessions dédiées.

## Contexte

Trigger initial : sondage 2026-05-05 sur les ~300 publis avec DOI
figshare. **229 sont des « Additional file X of … »** (suppléments PDF
figures/tableaux), classées « article » par OpenAlex donc remontées
comme telles dans la BDD UCA. La règle qui aurait dû les écarter
n'existe nulle part — il faut un endroit propre où l'écrire et la
tester.

Plusieurs autres règles métier sont aujourd'hui dispersées ou absentes
sur les variantes : figshare collection (`10.6084/m9.figshare.c.*`)
qui sont des bundles non canoniques, DOI Zenodo + titre suspect
(« Supplementary materials… »), DOI DataCite + `doc_type=article` mais
titre suspect.

## Objectif

Greffer dans `domain/` les nouvelles règles manquantes pour reclasser
les suppléments en `doc_type='other'` au lieu de `'article'`/
`'dataset'`, en restant cohérent avec le pattern « décision pure +
effets séparés » déjà éprouvé sur
[`resolve_doi_conflict`](../../domain/publication.py).

## Périmètre

### Inclus

- **Helpers de détection** par préfixe DOI / pattern titre :
  - `is_figshare_doi(doi)` (préfixe `10.6084/m9.figshare.*` et collections
    `10.6084/m9.figshare.c.*`)
  - `is_datacite_doi(doi)` (par préfixe — partiellement couvert par
    `doi_prefixes` après chantier
    [doi-ra-datacite](doi-ra-datacite.md), mais une fonction pure de
    détection prefix → RA reste utile pour les règles qui s'appliquent
    avant la table `doi_prefixes`).
  - `is_supplement_title(title)` : pattern « Additional file X of … »,
    « Supplementary material(s) for … », « Données supplémentaires
    de … », « Supporting information for … ». Multi-langue (FR + EN),
    regex compilées en module-level.
- **Politique « doc_type suspect »** : règle décisionnelle qui prend
  doc_type + DOI + titre + sources et renvoie un doc_type ajusté.
  Composée des helpers ci-dessus.
- **Extension** de `correct_openalex_doc_type`
  ([`domain/sources/openalex.py`](../../domain/sources/openalex.py))
  pour intégrer la cascade « DOI figshare/Zenodo/DataCite + titre
  supplément → doc_type = 'other' » en plus des règles theses.fr +
  dumas déjà en place.
- **Détection des suppléments orphelins** (le parent article n'est
  pas en BDD, cf. 145/229 cas figshare au 2026-05-05) → règle
  d'élimination ou marqueur explicite (à arbitrer).
- **Reclassement one-shot** des cas existants en fin de chantier (SQL
  aligné sur la nouvelle règle, suivi d'une passe de vérification au
  prochain run pipeline).

### Exclus

- Les **effets de bord** (SELECT/INSERT/UPDATE) restent en
  `application/` ou `infrastructure/`. Les algorithmes de décision
  qui les pilotent sont relocalisables — pattern déjà en place pour
  [`resolve_doi_conflict`](../../domain/publication.py) ↔
  `application/publications.py::resolve_doi_conflict`.
- L'ingestion DataCite proprement dite : couverte par
  [doi-ra-datacite.md](doi-ra-datacite.md). Ce chantier-ci se contente
  d'ajouter au `domain/` les règles que consommera DataCite quand il
  sera intégré.
- Refactors des cascades publications (find_or_create, merge, etc.) :
  fiche [`dedup-fusion-publications.md`](dedup-fusion-publications.md).
- Refactor de la cascade matching personnes : fiche
  [`decide-person-match.md`](decide-person-match.md).

## Plan d'implémentation

### Phase 2.A — helpers de détection

- [ ] `is_figshare_doi(doi)`, `is_datacite_doi(doi)` (sur préfixe) en
      `domain/publication.py` ou
      `domain/publications/identifiers.py` (à arbitrer).
- [ ] `is_supplement_title(title)` en
      `domain/publications/scope.py` ou un module dédié — patterns
      FR + EN, table de regex compilées en haut du module.
- [ ] Tests unitaires (positifs + faux positifs).

### Phase 2.B — politique doc_type suspect

- [ ] Étendre `correct_openalex_doc_type`
      ([`domain/sources/openalex.py`](../../domain/sources/openalex.py))
      pour intégrer la cascade « DOI figshare/Zenodo/DataCite + titre
      supplément → doc_type = 'other' ».
- [ ] Tests sur les ~300 cas figshare connus (snapshot avant/après).

### Phase 2.C — migration

- [ ] Lancer en dry-run sur la BDD existante : combien de publis
      seraient reclassées ? Comparer avec attendu (≥229 cas figshare
      « Additional file… »).
- [ ] Décider de la stratégie de migration :
      (a) UPDATE one-shot via SQL pour les publis existantes,
      (b) attendre le prochain run de pipeline qui réécrira les
      `source_publications` (mais `publications.doc_type` est calculé
      dans `refresh_from_sources` à partir des sources — il faudra
      relancer la phase de refresh).

## Décisions actées

1. **Granularité = dossier `domain/publications/` plutôt que fichiers
   plats à la racine de `domain/`**. Préfixe d'import explicite, rôle
   de chaque module immédiat à la lecture, évolution naturelle (sous-
   modules `domain/persons/`, `domain/structures/`).
2. **Reclassement one-shot des cas existants** en fin de chantier
   (SQL aligné + vérification au prochain run pipeline).
3. **Détection figshare/Zenodo : hardcoded au démarrage, via
   `doi_prefixes` quand le chantier
   [doi-ra-datacite](doi-ra-datacite.md) aura abouti**. Helpers
   `is_figshare_doi`/`is_zenodo_doi` à préfixe en dur (suffisant pour
   les patterns connus). Si après doi-ra-datacite on constate que
   `doi_prefixes` couvre l'intégralité des cas réels, on migrera
   entièrement et on retirera les helpers préfixe. Pas de double
   path à maintenir.

## Open questions

- **Suppléments orphelins** (145 cas figshare au 2026-05-05 dont le
  parent n'est pas en BDD) : à sonder au cas par cas en fin de
  chantier. Hypothèses à tester : (a) parent présent avec un titre
  légèrement différent (matching à raffiner), (b) parent réellement
  absent et c'est correct (publi non-UCA), (c) parent réellement
  absent à tort (à retrouver). Cette question rejoint un futur
  chantier de modélisation des **relations entre publications**
  (parent ↔ supplément, ouvrage ↔ chapitre, version ↔ révision, …)
  — à n'ouvrir qu'une fois ce chantier-ci abouti.

## Risques

- **Performance** : les regex de `is_supplement_title` doivent rester
  O(1) par titre — patterns compilés en module-level.
- **Coordination avec [doi-ra-datacite](doi-ra-datacite.md)** : la
  Phase 2.A peut bénéficier de `doi_prefixes` pour détecter
  `ra='DataCite'` plutôt que de hardcoder Zenodo + figshare. À
  séquencer après doi-ra-datacite phase 1, ou à mener en parallèle
  avec un fallback hardcodé.
- **Compatibilité avec
  [`refresh_from_sources`](../../application/publications.py)** :
  cette fonction recalcule le `doc_type` canonique depuis les sources
  (priorité theses.fr > ScanR > HAL > OpenAlex > WoS). Une nouvelle
  règle « doc_type suspect → other » doit s'appliquer **après** la
  sélection de la source prioritaire, ou être encodée dans le mapping
  de chaque source. À choisir : règle au niveau source (chaque
  normalizer corrige son propre `source_publications.doc_type`) ou
  règle au niveau canonique (`refresh_from_sources` applique
  l'override). Plus propre = au niveau source pour ne pas perdre
  l'info brute.

## Liens

- [doi-ra-datacite.md](doi-ra-datacite.md) — chantier jumeau,
  prérequis pour Phase 2.A (détection RA via préfixe)
- [crossref.md](crossref.md) — architecture CrossRef ingest
- [dedup-fusion-publications.md](dedup-fusion-publications.md) —
  cascade de déduplication / fusion publications (chantier dédié)
- [decide-person-match.md](decide-person-match.md) — cascade unifiée
  de matching personnes (chantier dédié)
