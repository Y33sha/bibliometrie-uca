# Chantier — Formalisation des règles métier dans `domain/`

## Contexte

Plusieurs règles métier sont aujourd'hui dispersées dans les scripts du
pipeline (`application/pipeline/normalize/*.py`), parfois dupliquées,
parfois conditionnelles à un détail d'extraction d'une source précise.
Exemples :

- `doc_type = "thesis"` si la `source = theses.fr`, indépendamment du
  type prétendu par OpenAlex
  ([normalize_openalex.py:270](application/pipeline/normalize/normalize_openalex.py#L270))
- `doc_type = "memoir"` si OpenAlex annonce `dissertation` et l'URL
  est `dumas.*` ([normalize_openalex.py:273-276](application/pipeline/normalize/normalize_openalex.py#L273-L276))
- `doc_type = "thesis" if dateSoutenance else "ongoing_thesis"` —
  dupliqué deux fois dans
  [normalize_theses.py](application/pipeline/normalize/normalize_theses.py) (l. 88, 247)
- Détection de la source figshare/Zenodo via DOI : éparpillée
  ([is_zenodo_doi](domain/zenodo.py) en domain, mais la détection
  figshare n'existe pas)
- Logique de rattachement personnes (matching ORCID/idHAL/idref →
  persons, gestion des conflits) : éclatée entre `application/persons.py`,
  les normalizers et les queries
- Règles de déduplication publications (matching DOI / NNT / titre) :
  partagées entre `find_or_create_publication`, `try_merge_by_doi` et
  les normalizers source par source

Le risque : règles invisibles aux tests unitaires de domaine (qui ne
voient que les fonctions pures relocalisées), divergences silencieuses
entre sources (ex. règle de doc_type différente selon le normalizer qui
écrit la publi en premier), évolutions difficiles (ajouter une règle
oblige à toucher N normalizers).

Trigger immédiat : sondage 2026-05-05 sur les ~300 publis avec DOI
figshare. **229 sont des « Additional file X of … »** (suppléments PDF
figures/tableaux), classées « article » par OpenAlex donc remontées
comme telles dans la BDD UCA. La règle qui aurait dû les écarter
n'existe nulle part — il faut un endroit propre où l'écrire et la
tester.

## Objectif

Rassembler dans `domain/` la logique métier pure, indépendante des
sources et de l'infrastructure, puis y greffer les nouvelles règles
manquantes (suppléments figshare, Zenodo, DataCite suspects).

Hypothèse de travail : les règles vivent dans `domain/` sous forme de
fonctions pures + dataclasses immuables, testées en unit pur (sans
BDD). Les normalizers consomment ces fonctions au lieu d'inliner les
conditions.

## Périmètre fonctionnel

### Inclus

- **Inventaire** des règles métier actuellement inlinées dans
  `application/pipeline/normalize/*.py`,
  `application/persons.py`,
  `application/publications.py` et identification de celles qui sont
  pures (pas d'I/O, pas de cur, pas de repo).
- **Relocation** dans `domain/` des fonctions pures identifiées,
  regroupées par concept (`domain/publication.py`,
  `domain/doc_types.py`, `domain/person_matching.py` à créer, etc.).
- **Tests unitaires purs** pour chaque règle relocalisée.
- **Refactor** des normalizers pour consommer les fonctions de
  `domain/` au lieu de leurs versions inlinées.
- **Nouvelles règles** pour les cas suspects :
  - DOI figshare (`10.6084/m9.figshare.*`) avec titre `Additional file…`
    → `doc_type = 'other'` au lieu de `article`/`dataset`
  - DOI figshare collection (`10.6084/m9.figshare.c.*`) avec titre
    article → traiter comme `'other'` également (ce sont des bundles
    qui ne sont pas la publi canonique)
  - DOI Zenodo (`10.5281/zenodo.*`) + titre suspect
    (« Supplementary materials… », « Données supplémentaires… ») →
    idem
  - DOI DataCite (au sens RA) + `doc_type = article` mais titre
    suspect → reclassement
- **Détection des suppléments orphelins** (le parent article n'est
  pas en BDD, cf. 145/229 cas figshare au 2026-05-05) → règle
  d'élimination ou marqueur explicite (à arbitrer).

### Exclus

- Les règles **non pures** (rattachement persons qui demande un repo,
  fusion de publications qui demande SQL transactionnel) restent dans
  `application/`. Le chantier rapatrie dans `domain/` la **partie
  décisionnelle** (la fonction qui dit quoi faire, sans le faire),
  laissant la partie effets de bord en `application/`.
- L'ingestion DataCite proprement dite : couverte par le chantier
  [doi-ra-datacite.md](docs/chantiers/doi-ra-datacite.md).
  Ce chantier-ci se contente d'ajouter au `domain/` les règles que
  consommera DataCite quand il sera intégré.
- Modifications du schéma SQL : le chantier porte sur la couche
  business pure, pas sur la persistance. Les règles peuvent suggérer
  d'ajouter une colonne (ex. `publications.doc_type_overridden`) ;
  ces décisions seront prises au cas par cas.
- Règles de scoring / ranking de fusion HAL × OpenAlex × WoS : sujet
  distinct (cf. `merge_pubs_by_hal_id.py`).

## État des lieux — règles déjà en `domain/`

À ce jour, [`domain/`](domain/) contient :

- [`domain/publication.py`](domain/publication.py) :
  - VOs `DOI`, `HALId`, `NNT` (validation, normalisation)
  - `clean_doi`, `clean_publication_title`
  - `resolve_doi_conflict` : décide quoi faire quand un DOI nouveau
    arrive en conflit avec une publi existante (pure, déjà bien isolée)
  - `best_oa_status` : choix du statut OA le plus ouvert dans une liste
- [`domain/doc_types.py`](domain/doc_types.py) :
  `_SOURCE_MAPS` + `map_doc_type(raw, source)` (pur, table de
  correspondance source → enum canonique)
- [`domain/zenodo.py`](domain/zenodo.py) : `is_zenodo_doi` + classe
  d'erreur (utilisée par les normalizers HAL/OpenAlex)
- [`domain/names.py`](domain/names.py) : parsing nom complet,
  `names_compatible` (matching personnes)
- [`domain/normalize.py`](domain/normalize.py) : `normalize_text`,
  `normalize_name_form`
- [`domain/sources.py`](domain/sources.py) : constantes de sources et
  priorités

Le pattern à reproduire : fonctions pures, sans `cur`/`repo`/`async`,
testables sans BDD.

## État des lieux — règles inlinées à rapatrier

### `domain/doc_types.py` à enrichir

À déplacer / ajouter :

- **Override par source authoritative** : aujourd'hui, dans
  [normalize_openalex.py:270-276](application/pipeline/normalize/normalize_openalex.py#L270-L276),
  le code force `doc_type = "thesis"` quand `is_theses_fr_source(work)`,
  ou `"memoir"` quand `dissertation + dumas`. Ces règles devraient être
  exposées sous la forme :
  ```python
  def override_doc_type_from_signals(
      raw: str | None,
      source: str,
      *,
      is_theses_fr: bool = False,
      landing_page_url: str | None = None,
      doi: str | None = None,
      title_normalized: str | None = None,
  ) -> str:
      """Applique la cascade d'overrides : la source canonique gagne sur
      la nomenclature OpenAlex. Pure."""
  ```
- **Règle « doc_type theses »** : `thesis` ou `ongoing_thesis` selon
  présence de `dateSoutenance` — actuellement dupliquée dans
  [normalize_theses.py](application/pipeline/normalize/normalize_theses.py)
  (l. 88 et 247). Une seule fonction `theses_doc_type(date_soutenance)`
  en domain.

### `domain/publication.py` à enrichir

- **Détection de suppléments par titre** : pattern « Additional file
  X of … », « Supplementary material(s) for … », « Données
  supplémentaires de … », « Supporting information for … » →
  `is_supplement_title(title) -> bool`. Multi-langue (FR + EN).
- **Détection figshare / DataCite** : `is_figshare_doi`,
  `is_datacite_doi` (par préfixe — partiellement couvert par
  `doi_prefixes` après chantier doi-ra-datacite, mais une fonction
  pure de détection prefix → RA reste utile pour les règles qui
  s'appliquent **avant** la table doi_prefixes).
- **Politique « doc_type suspect »** : règle décisionnelle qui prend
  doc_type + DOI + titre + sources et renvoie un doc_type ajusté ou
  un flag "suspect". Composée des helpers ci-dessus.

### `domain/person_matching.py` (à créer)

La logique de matching personne dispersée entre :

- `application/persons.py` (matching par identifiers, gestion des
  status pending/confirmed/rejected)
- `application/pipeline/persons/build_authorships.py`
- les normalizers HAL/OpenAlex/WoS/ScanR/theses (chacun écrit ses
  `source_authorships` avec son propre `person_id` selon des règles
  variables)

À identifier :
- Règles **pures** (ex. « si ORCID et idHAL convergent vers la même
  person, on lie ; sinon on crée pending »)
- Règles **non pures** (ex. transaction SQL qui mute
  `person_identifiers`) → restent en `application/`

### `domain/publication_dedup.py` (à créer ?)

La déduplication publications est répartie entre :
- `application/publications.py::find_or_create`,
  `try_merge_by_doi`, `merge_publications`,
  `resolve_doi_conflict` (ce dernier est déjà pur en domain ✅)
- `infrastructure/repositories/publication_repository.py::find_by_doi`,
  `find_by_nnt`, `merge_into`

À extraire : règles de matching (DOI > NNT > titre+année), règles
d'arbitrage en cas de conflit, règles de fusion de métadonnées (déjà
documentées dans `refresh_from_sources` mais le code est en
`application/`).

## Architecture cible

```
domain/
├── publication.py          ← +is_supplement_title, +is_figshare_doi, +is_datacite_doi, +ajustement doc_type suspect
├── doc_types.py            ← +override_doc_type_from_signals, +theses_doc_type
├── person_matching.py      ← (nouveau) règles pures de matching personne
├── publication_dedup.py    ← (nouveau) règles pures de déduplication
└── …
```

Les normalizers consomment ces fonctions :

```python
# application/pipeline/normalize/normalize_openalex.py
from domain.doc_types import override_doc_type_from_signals
from domain.publication import is_supplement_title

def extract_pub_metadata(work, journal_id):
    raw_type = work.get("type") or "other"
    doc_type = override_doc_type_from_signals(
        raw_type,
        source="openalex",
        is_theses_fr=is_theses_fr_source(work),
        landing_page_url=(work.get("primary_location") or {}).get("landing_page_url"),
        doi=clean_doi(work.get("doi")),
        title_normalized=normalize_text(work.get("title") or ""),
    )
    # ... le reste inchangé
```

## Phases d'implémentation

### Phase 0 — Inventaire complet
- [ ] Lister toutes les fonctions/blocs `application/pipeline/normalize/*`
      et `application/{persons,publications}.py` qui contiennent une
      règle métier (≠ orchestration).
- [ ] Pour chaque règle, classer : (a) déjà pure → relocalisable
      directement, (b) non pure → décomposable en partie pure +
      effets, (c) intrinsèquement liée à la transaction → reste en
      `application/`.
- [ ] Note de synthèse listant les fonctions à créer côté `domain/`.
- **Livrable** : fichier `docs/chantiers/regles-metier-inventaire.md`
  (ou section ajoutée à ce doc).

### Phase 1 — Relocations sans changement de comportement
- [ ] Déplacer `is_theses_fr_source` de
      `application/pipeline/normalize/openalex_parsing.py` vers
      `domain/` (c'est une règle pure sur un dict OpenAlex — préfixe
      du `primary_location.source.id`).
- [ ] Créer `theses_doc_type(date_soutenance)` en `domain/doc_types.py`,
      remplacer les 2 occurrences inlinées dans `normalize_theses.py`.
- [ ] Créer `override_doc_type_from_signals(...)` en
      `domain/doc_types.py`, intégrant la cascade actuelle (theses.fr
      → thesis, dissertation+dumas → memoir). Remplacer le bloc dans
      `normalize_openalex.py:270-276`.
- [ ] Tests unitaires purs sur ces fonctions (snapshots de doc_type
      attendu pour des inputs réels prélevés dans la BDD).
- **Livrable** : fonctions relocalisées, comportement strictement
  inchangé, tests verts. Couverture qui augmente côté domain.

### Phase 2 — Nouvelles règles « suspects »
- [ ] `is_figshare_doi(doi)`, `is_datacite_doi(doi)` (sur préfixe) en
      `domain/publication.py`.
- [ ] `is_supplement_title(title)` en `domain/publication.py` —
      patterns FR + EN, table de regex compilées en haut du module.
- [ ] Étendre `override_doc_type_from_signals` pour intégrer la
      cascade « DOI figshare/Zenodo/DataCite + titre supplément →
      doc_type = 'other' ». Tests sur les ~300 cas figshare connus
      (snapshot avant/après).
- [ ] Lancer en dry-run sur la BDD existante : combien de publis
      seraient reclassées ? Comparer avec attendu (≥229 cas figshare
      « Additional file… »).
- [ ] Décider de la stratégie de migration :
      (a) UPDATE one-shot via SQL pour les publis existantes,
      (b) attendre le prochain run de pipeline qui réécrira les
      `source_publications` (mais `publications.doc_type` est calculé
      dans `refresh_from_sources` à partir des sources — il faudra
      relancer la phase de refresh).
- **Livrable** : règles nouvelles testées + plan de migration des
  données existantes.

### Phase 3 — Person matching / dedup publications
- [ ] À cadrer **après** phase 1-2, en fonction de l'apprentissage.
      Périmètre potentiellement plus large, à scinder éventuellement
      en chantier dédié.

## Décisions à prendre

1. **Granularité du module `domain/publication.py`** : il commence à
   être gros (~600 lignes). Faut-il scinder en `domain/publication.py`
   (VOs, métadonnées) + `domain/publication_rules.py` (règles
   décisionnelles) ? Plutôt oui pour la lisibilité.
2. **Stratégie pour les cas figshare existants** : reclassement
   one-shot ou attendre le prochain refresh ? Le one-shot est plus
   propre côté UI immédiate, le refresh est plus cohérent avec le
   pipeline. Hypothèse : one-shot SQL qui s'aligne sur la nouvelle
   règle, suivi d'une vérification au prochain run que le pipeline
   produit le même résultat.
3. **Suppléments orphelins** : que faire des 145 figshare suppléments
   dont le parent n'est pas en BDD ? Options : (a) les garder mais
   marqués `other`, (b) les exclure du périmètre UCA (les retirer du
   reporting), (c) les filtrer à l'extraction OpenAlex (ne pas les
   ingérer du tout). À arbitrer en concertation avec la cliente.
4. **DataCite vs CrossRef pour la détection** : avant le chantier
   doi-ra-datacite, on peut détecter via préfixe DOI hardcodé
   (Zenodo = 10.5281, figshare = 10.6084). Après, via la table
   `doi_prefixes`. Faut-il maintenir les deux paths (fallback) ou
   migrer entièrement quand `doi_prefixes` existe ?

## Risques & open questions

- **Tests longs à écrire** pour les règles relocalisées : il faut
  des fixtures réalistes (sample de docs OpenAlex/HAL/theses
  capturé en JSON). Compromis : démarrer avec des fixtures
  minimales, enrichir au fil des bugs.
- **Performance** : les nouvelles regex de `is_supplement_title`
  doivent rester O(1) par titre — patterns compilés en module-level.
- **Coordination avec [chantier doi-ra-datacite.md](docs/chantiers/doi-ra-datacite.md)** :
  la phase 2 de ce chantier-ci peut bénéficier de `doi_prefixes`
  pour détecter `ra='DataCite'` plutôt que de hardcoder Zenodo +
  figshare. À séquencer après doi-ra-datacite phase 1, ou à mener
  en parallèle avec un fallback hardcodé.
- **Compatibilité avec [refresh_from_sources](application/publications.py)** :
  cette fonction recalcule le `doc_type` canonique depuis les
  sources (priorité theses.fr > ScanR > HAL > OpenAlex > WoS). Une
  nouvelle règle « doc_type suspect → other » doit s'appliquer
  **après** la sélection de la source prioritaire, ou être encodée
  dans le mapping de chaque source. À choisir : règle au niveau
  source (chaque normalizer corrige son propre `source_publications.doc_type`)
  ou règle au niveau canonique (refresh_from_sources applique
  l'override). Plus propre = au niveau source pour ne pas perdre
  l'info brute.

## Liens

- [doi-ra-datacite.md](docs/chantiers/doi-ra-datacite.md) — chantier
  jumeau, prérequis pour la phase 2 (détection RA via préfixe)
- [crossref.md](docs/chantiers/crossref.md) — architecture CrossRef
  ingest (modèle pour DataCite)
- Fichiers à toucher en priorité (phase 1) :
  - [`domain/doc_types.py`](domain/doc_types.py)
  - [`domain/publication.py`](domain/publication.py)
  - [`application/pipeline/normalize/normalize_openalex.py`](application/pipeline/normalize/normalize_openalex.py) (l. 270-276)
  - [`application/pipeline/normalize/normalize_theses.py`](application/pipeline/normalize/normalize_theses.py) (l. 88, 247)
  - [`application/pipeline/normalize/openalex_parsing.py`](application/pipeline/normalize/openalex_parsing.py) (l. 13)
- Trigger initial : sondage figshare 2026-05-05 (cf. discussion
  conversation, ~300 publis dont 229 « Additional file… » classées
  abusivement comme article par OpenAlex).
