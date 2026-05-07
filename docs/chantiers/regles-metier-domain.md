# Chantier — Formalisation des règles métier dans `domain/`
Commencé le 2026-05-05

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

**Définition de « pur »** : une fonction qui prend en arguments tout
ce dont elle a besoin (y compris les résultats de lookups SQL faits
par la couche application) et qui renvoie une décision (souvent un
value object). Les algorithmes de matching personnes, de
déduplication publications, d'arbitrage doc_type relèvent tous de ce
modèle — l'arbre de décision est pur, ce sont les SELECT en amont et
les INSERT/UPDATE en aval qui sont impurs et restent en
`application/`. Pattern déjà éprouvé sur
[`resolve_doi_conflict`](domain/publication.py#L553).

Hypothèse de travail : les règles vivent dans `domain/` sous forme de
fonctions pures + dataclasses immuables, testées en unit pur (sans
BDD). Les normalizers et services applicatifs consomment ces fonctions
au lieu d'inliner les conditions.

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

- Les **effets de bord** (SELECT/INSERT/UPDATE, gestion de
  transactions, appels API externes) restent en `application/` ou
  `infrastructure/`. Mais les **algorithmes de décision** qui les
  pilotent sont relocalisables : on extrait dans `domain/` la fonction
  pure qui prend en entrée le résultat des lookups (déjà faits par la
  couche application) et renvoie une décision (value object), puis
  l'application applique l'effet. Pattern déjà en place pour
  [`resolve_doi_conflict`](domain/publication.py#L553) ↔
  [`application/publications.py::resolve_doi_conflict`](application/publications.py).
- L'ingestion DataCite proprement dite : couverte par le chantier
  [doi-ra-datacite.md](docs/chantiers/doi-ra-datacite.md).
  Ce chantier-ci se contente d'ajouter au `domain/` les règles que
  consommera DataCite quand il sera intégré.
- Modifications du schéma SQL : le chantier porte sur la couche
  business pure, pas sur la persistance. Les règles peuvent suggérer
  d'ajouter une colonne (ex. `publications.doc_type_overridden`) ;
  ces décisions seront prises au cas par cas.

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

L'**algorithme** de matching personne est pur — il prend les résultats
de lookups (faits par la couche application) et renvoie une décision.

Hiérarchie de fiabilité retenue (de la plus fiable à la moins) :

1. **ORCID Crossref** : un ORCID dans Crossref vient de l'éditeur
   donc directement de l'auteur lors de la soumission. Le plus fiable.
2. **Compte HAL** (`hal_person_id`) : identifie un compte créé par
   l'auteur ou par un curateur ; quelques erreurs de rattachement
   possibles mais globalement fiable.
3. **Idref / ORCID provenant d'autres sources** (HAL hors compte,
   OpenAlex, WoS) : les ORCID OpenAlex/WoS viennent souvent d'un
   matching par nom côté éditeur de la source, donc régulièrement
   fautifs. À surveiller — voire à retirer si l'analyse confirme un
   ratio bruit/signal défavorable.
4. **Matching par nom** : dernier recours, avec arbitrage sur l'unicité
   du résultat.

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class PersonMatchDecision:
    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: str = ""
    # 'orcid_crossref' | 'hal_account' | 'orcid_or_idref_other_source'
    # | 'single_name' | 'name_ambiguous' | …

def decide_person_match(
    *,
    orcid_crossref_match: int | None,      # ORCID issu de Crossref
    hal_account_match: int | None,         # hal_person_id
    orcid_idref_other_matches: list[int],  # ORCID/idref de HAL hors compte, OA, WoS
    name_matches: list[int],               # matching par nom normalisé
) -> PersonMatchDecision:
    """Cascade de matching, du signal le plus fiable au moins fiable.
    Pure, testable sans BDD."""
    if orcid_crossref_match is not None:
        return PersonMatchDecision("match", orcid_crossref_match, "orcid_crossref")
    if hal_account_match is not None:
        return PersonMatchDecision("match", hal_account_match, "hal_account")
    if len(orcid_idref_other_matches) == 1:
        return PersonMatchDecision("match", orcid_idref_other_matches[0],
                                   "orcid_or_idref_other_source")
    if len(orcid_idref_other_matches) > 1:
        return PersonMatchDecision("skip", reason="orcid_idref_ambiguous")
    if len(name_matches) == 1:
        return PersonMatchDecision("match", name_matches[0], "single_name")
    if len(name_matches) > 1:
        return PersonMatchDecision("skip", reason="name_ambiguous")
    return PersonMatchDecision("create")
```

Côté `application/` : `match_person_for_authorship(...)` orchestre les
SELECT, appelle `decide_person_match`, applique l'effet selon la
décision (INSERT person + identifiers, ou attache person_id existant,
ou skip). C'est le pattern déjà utilisé par
[`resolve_doi_conflict`](domain/publication.py#L553).

À rapatrier de `application/persons.py` et de
`application/pipeline/persons/build_authorships.py` :
- les règles d'arbitrage (ordre des sources d'identité, comportement
  en cas d'ambiguïté, gestion des statuts `pending`/`confirmed`/
  `rejected` côté `person_identifiers`)
- les invariants métier (ex. « jamais de fusion automatique entre
  deux persons ayant chacune un `persons_rh` distinct » — déjà
  appliqué côté API et scripts, à formaliser comme fonction pure)

**Question ouverte — matching par co-publication** : actuellement
utilisé en complément du matching par nom pour désambiguïser (« on
relie cette signature à la person X parce qu'elle a déjà co-signé une
publi avec Y, et Y est aussi auteur ici »). Pose problème sur les
méga-papers (consortiums, papers à 100+ auteurs) avec des
désalignements fréquents. À réexaminer pendant ce chantier :
maintien tel quel, restriction à un seuil max d'auteurs (ex.
≤ 30 auteurs), ou suppression. Décision à prendre après mesure du
ratio matchings utiles / faux positifs sur les cas méga-paper.

### `domain/publication_dedup.py` (à créer)

Même pattern que pour les personnes : l'algorithme de déduplication
est pur, on extrait la fonction de décision.

```python
@dataclass(frozen=True)
class PublicationMatchDecision:
    action: Literal["match", "create"]
    publication_id: int | None = None
    reason: str = ""  # 'doi' | 'nnt' | 'title_year' | …

def decide_publication_match(
    *,
    doi_match: int | None,                 # find_by_doi
    nnt_match: int | None,                 # find_by_nnt
    title_year_matches: list[int],         # find_by_title_year
) -> PublicationMatchDecision:
    """Cascade DOI > NNT > titre+année. Pure."""
    if doi_match is not None:
        return PublicationMatchDecision("match", doi_match, "doi")
    if nnt_match is not None:
        return PublicationMatchDecision("match", nnt_match, "nnt")
    if len(title_year_matches) == 1:
        return PublicationMatchDecision("match", title_year_matches[0], "title_year")
    return PublicationMatchDecision("create")
```

Pour la **fusion** de publications, même approche : on extrait
`decide_merge_strategy(target: PubMeta, source: PubMeta) -> MergeDecision`
qui dit champ par champ quoi écraser, quoi garder, quoi fusionner
(union pour les listes, max pour `oa_status` selon priorité, etc.).
La logique est déjà documentée dans
[`refresh_from_sources`](application/publications.py#L297) — il s'agit
de la rendre testable comme fonction pure.

À rapatrier :
- la cascade DOI > NNT > titre+année dispersée dans
  [`find_or_create`](application/publications.py)
- les règles de fusion (priorité par source, OA "le plus ouvert
  gagne", union de countries) embarquées dans `refresh_from_sources`
- les invariants de fusion (jamais de fusion qui casserait
  l'unicité DOI, déjà géré par `try_merge_by_doi` mais à formaliser)
- la **liste des identifiants candidats à la déduplication** et leurs
  exceptions, exprimée comme donnée métier plutôt qu'en dur dans
  l'algorithme :
  ```python
  @dataclass(frozen=True)
  class DedupIdentifier:
      name: str                        # 'doi', 'hal_id', 'nnt', 'pmid', …
      priority: int                    # ordre de la cascade
      blocks_merge_when: tuple[str, ...] = ()  # ex. ('doc_type_mismatch_chapter_book',)

  DEDUP_IDENTIFIERS = (
      DedupIdentifier("doi",    priority=1, blocks_merge_when=("chapter_vs_book",)),
      DedupIdentifier("nnt",    priority=2),
      DedupIdentifier("hal_id", priority=3),
      # DedupIdentifier("pmid",  priority=4),  # le jour où on en aura
  )
  ```
  Exceptions concrètes à formaliser :
  - **DOI chapitre vs ouvrage** : un même DOI peut identifier un
    chapitre (`book_chapter`) ET l'ouvrage entier (`book`) chez
    certains éditeurs. Pas de fusion automatique entre les deux.
  - **DOI dataset vs article** (cf. trigger figshare) : un DOI Zenodo/
    figshare peut être lié à un article par `relatedIdentifier` mais
    n'EST pas l'article. Pas de match par DOI dans ce sens.
  - **NNT vs DOI** : la priorité actuelle (DOI > NNT) suppose que
    quand deux thèses partagent un NNT mais ont des DOI différents,
    elles sont distinctes. À documenter explicitement.

  Le scoring / ranking de fusion HAL × OpenAlex × WoS (déjà partiellement
  dans [`merge_pubs_by_hal_id.py`](application/pipeline/publications/merge_pubs_by_hal_id.py))
  rentre dans ce cadre : les règles deviennent une fonction pure qui
  consomme `DEDUP_IDENTIFIERS` + les exceptions.

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
- [x] Lister toutes les fonctions/blocs `application/pipeline/normalize/*`
      et `application/{persons,publications}.py` qui contiennent une
      règle métier (≠ orchestration).
- [x] Pour chaque règle, classer : (a) déjà pure → relocalisable
      directement, (b) non pure → décomposable en partie pure +
      effets, (c) intrinsèquement liée à la transaction → reste en
      `application/`.
- [x] Note de synthèse listant les fonctions à créer côté `domain/`.
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
- [ ] Créer `domain/person_matching.py` avec `decide_person_match` +
      `PersonMatchDecision`. Tests unitaires sur les 5+ branches de
      l'arbre.
- [ ] Refactor `application/persons.py` (et le caller dans
      `build_authorships`) pour : prefetch des 3 listes
      (hal_account_match, orcid_idref_matches, name_matches), appel
      `decide_person_match`, application de la décision.
- [ ] Idem `domain/publication_dedup.py` :
      `decide_publication_match` + `decide_merge_strategy`. Tests sur
      cascade DOI/NNT/titre et règles de fusion.
- [ ] Refactor `application/publications.py::find_or_create` et
      `refresh_from_sources` pour consommer ces fonctions pures.
- [ ] Vérifier que la couverture des règles métier en domain/ est
      exhaustive : aucune règle décisionnelle restante en application/
      hors prefetch + apply.

## Journal des relocations

Trace minimale des items rapatriés au fil de l'eau (entrée
correspondante supprimée de `regles-metier-inventaire.md` au même
moment). Le détail métier vit dans les docstrings des fonctions
relocalisées en `domain/`.

- **ORCID — normalisation unifiée** : `_normalize_orcid` de
  `domain/person.py` rendue publique (`normalize_orcid`). Appliquée
  dans les 5 normalizers (HAL, OpenAlex, Crossref, WoS, ScanR), qui
  abandonnent leurs versions inlinées. Durcissement : ORCID malformé
  → `None` au lieu d'être stocké tel quel — préférable côté
  comparabilité avec `person_identifiers`. Suppression au passage
  de `interfaces/cli/crossref_spike.py` (one-shot phase 0
  crossref, livrable terminé).
- **`is_wos_author_exploitable` rapatriée** : filtre WoS « auteur
  exploitable = `daisng_id` + `full_name` non vides » sorti de
  `normalize_wos.py` vers `domain/sources/wos.py`. Le `daisng_id` n'est
  plus une clé d'unicité côté DB depuis le chantier source_persons,
  mais reste un signal de qualité du parsing API WoS — son absence
  signale un enregistrement douteux à écarter. 4 tests unitaires.
- **`extract_thesis_year` rapatriée + déduplication** : règle
  « pub_year = soutenance, sinon première inscription » dupliquée
  verbatim dans `extract_pub_metadata` et `insert_source_document`
  de `normalize_theses.py`. Fonction unique
  `extract_thesis_year(date_soutenance, date_inscription)` ajoutée
  dans `domain/sources/theses.py`. Format `JJ/MM/AAAA` géré par un
  helper privé `_year_from_theses_date`. Tests unitaires (5 cas).
- **`extract_nnt_from_scanr_id` rapatriée** : de
  `application/pipeline/normalize/normalize_scanr.py` (helper privé
  `_extract_nnt_from_scanr_id`) vers `domain/sources/scanr.py`. Convention
  ScanR : un `scanr_id` qui commence par `these` encode un NNT
  (ex. `these2021CLFAC030`). Tests unitaires ajoutés dans
  `tests/unit/domain/sources/test_scanr.py`.
- **`compute_person_name_forms` déplacée** : de `domain/person.py`
  vers `domain/names.py` (homogène avec `parse_raw_author_name` et
  les autres helpers de format de nom). Le réexport
  `application.persons.compute_person_name_forms` est supprimé ;
  les 7 call sites (pipeline, repos sync/async, tests) importent
  désormais directement depuis `domain.names`. La fonction elle-même
  était déjà en domain — l'item d'inventaire portait sur
  l'organisation, pas sur la migration.
- **CrossRef — 4 helpers purs rapatriés** : nouveau module
  `domain/sources/crossref.py` regroupant `strip_jats_tags(s)`
  (retire les balises XML JATS de l'abstract), `extract_crossref_pub_year(msg, *, max_year)`
  (cascade `published > issued > published-online > published-print`,
  clamp `[1500, max_year]`), `parse_crossref_issns(msg)` (sépare
  ISSN print et eissn via `issn-type`, fallback sur le premier `ISSN`
  brut) et `extract_crossref_meta(msg)` (whitelist
  `license`/`funder`/`relation`/`references_count`/`indexed.timestamp`).
  `max_year` est désormais un paramètre injecté (testabilité), le
  caller passe `datetime.date.today().year + 1`. Les fonctions
  `get_pub_year`/`get_issns`/`get_abstract`/`get_meta` du normalizer
  deviennent de fines adaptatrices locales (1-4 lignes) qui injectent
  le contexte calendrier ou le None-handling autour de la fonction
  domain. Tests déplacés dans `tests/unit/domain/sources/test_crossref.py`.
- **ScanR `select_leaf_affiliations` rapatriée** : `select_labo_affiliations`
  de `normalize_scanr.py` migrée vers `domain/sources/scanr.py` et
  renommée en `select_leaf_affiliations` (symétrie avec
  `authIdHasPrimaryStructure_fs` côté HAL — préférence des feuilles
  laboratoires sur l'arbre aplati incluant les tutelles parentes).
  Sémantique inchangée : ne conserve que les affiliations marquées
  `id_name_author_labo`, fallback sur la liste complète sinon.
- **Theses `thesis_authors_compatible` rapatriée** : la décision pure
  de compatibilité auteur (cascade `names_compatible` → fallback tokens
  identiques pour particules type « Le », « Ben », « Da ») descend dans
  `domain/sources/theses.py`. Le wrapper application
  `_thesis_author_compatible` ne fait plus que le SELECT
  `fetch_thesis_primary_author` puis délègue. Tests rapatriés dans
  `tests/unit/domain/sources/test_theses.py` (plus besoin de stub
  `queries`, on appelle la fonction pure directement).
- **OpenAlex `extract_external_ids_from_urls` rapatriée** : la décision
  pure « URL → quelles IDs en sortir » (regex HAL/NNT/PMID/PMC, premier
  match par type gagnant) descend dans `domain/sources/openalex.py`. Le
  wrapper application `extract_locations_data` se réduit à la
  construction de la liste d'URLs (parsing dict OpenAlex
  `landing_page_url` + `pdf_url` dédupliqués) puis délégation. Pas de
  `normalize_nnt` côté extracteur — c'est un extracteur opportuniste,
  la normalisation est laissée au caller.
- **OpenAlex `keep_orcid_if_name_matches` rapatriée** : la règle qui
  filtre l'ORCID porté par une entité auteur OpenAlex selon la
  compatibilité du nom avec le `raw_author_name` de l'authorship
  descend dans `domain/sources/openalex.py`. Garde-fou contre les
  mauvaises assignations auteur×signature côté OpenAlex (qui hériteraient
  un ORCID erroné). Le call site dans `create_persons_from_source_authorships`
  passe de 9 lignes à 5.
- **Item « enrichissement d'une forme par fusion de sources » retiré de
  l'inventaire** : la fusion d'arrays `person_ids ∪ sources` dans
  `populate_person_name_forms` n'est qu'un symptôme du schéma denormalisé
  `person_name_forms(name_form, person_ids[], sources[])`. La
  factorisation gagne peu (single call site, logique triviale) et la
  boucle entière disparaîtra avec le chantier de normalisation noté
  dans `TODO_CLAUDE.md` (schéma cible : row-per-triple). Pas de
  rapatriement domain.
- **Suppression de la règle de préservation dans `populate_person_name_forms`** :
  l'item d'inventaire « règle de préservation des formes non
  bibliographiques » s'est révélé être un effet pervers d'un autre choix
  (le filtre `rejected = FALSE` dans `fetch_active_persons_names`) plutôt
  qu'une règle métier.

  Investigation : la règle préservait défensivement les formes avec
  `source = persons` ou `manual` quand la recalculation ne les
  produisait plus. `manual` est dead code (aucun INSERT ne l'écrit).
  Pour `persons`, la cause d'orphelin était presque exclusivement les
  rejected — qui sont les artefacts de parsing source / noms
  d'organisations / chaînes mal parsées. Or ces formes DOIVENT rester
  pour servir d'ancre de matching et empêcher la re-création en boucle
  au prochain run pipeline.

  Refactor : retirer `AND rejected = FALSE` dans `fetch_active_persons_names`
  (renommée `fetch_persons_names`) → les rejected entrent dans la
  recalculation, leurs forms restent dans `expected_forms` et survivent
  naturellement au diff. Plus besoin de règle de préservation : toute
  forme dans `existing - expected_forms` est supprimée par construction
  (plus aucune source ne la soutient). Variable `new_forms` renommée
  `expected_forms` au passage (le nom précédent était trompeur).

  Aucun changement comportemental : les 82 formes préservées en BDD
  aujourd'hui restent en place, mais portées par la cohérence de la
  recalculation plutôt que par une règle défensive cachée.

  L'item est **retiré de l'inventaire** plutôt que rapatrié — c'était
  une mauvaise modélisation initiale.
- **`has_minimal_publication_metadata` ajouté à `domain/publications/dedup.py`** :
  invariant « titre non vide + année renseignée requis pour
  créer/dédupliquer une publication » factorisé depuis 6 sites
  dupliqués (`application/publications.py:155`,
  `pipeline/publications/create_publications.py:43`, et 4 normalizers
  HAL/ScanR/Crossref). Nouveau fichier `dedup.py` dans le dossier
  `domain/publications/` ouvert précédemment, qui accueillera la
  cascade de matching DOI/NNT/title+year+journal et les invariants
  associés.
- **`decide_cross_source_match` ajouté à `domain/persons/matching.py`** :
  factorisation de l'étape 1 du pipeline persons (rattachement par
  `(publication_id, author_position)` à une `person_id` connue d'une
  autre source, avec garde-fou `names_compatible`). Décision pure :
  prend la liste des candidats prefetchée et renvoie la `person_id`
  unique compatible, ou `None` (aucun match ou conflit ≥2 person_ids
  distincts). TODO follow-up dans `TODO_CLAUDE.md` : seuil sur le
  nombre d'auteurs total pour éviter les faux conflits sur les
  méga-papers (cohérent avec `MAX_AUTHORS_CONFLICT` de
  `TODO_LAURA.md`).
- **`decide_name_form_outcome` ajouté à `domain/persons/matching.py`** :
  factorisation de l'arbitrage du résultat de lookup name_form en
  décision pure. Trois actions cohérentes (`match`, `create`, `skip`)
  remplaçant le mélange état/action de la version inline (`match`,
  `ambiguous`, `create`). Le `reason` du `skip` capture la nuance
  (`ambiguous_name_form` vs `creation_not_allowed`) pour les logs.
  Compteur local côté `step3_name_forms` renommé `ambiguous` → `skipped`
  pour cohérence avec le vocabulaire domain. Pattern symétrique à
  `resolve_doi_conflict` côté publication.
- **Simplification de `step3_name_forms` — drop de la cascade redondante** :
  l'item d'inventaire « cascade de lookup par name_form » s'est révélé
  être une duplication de logique plutôt qu'une règle à factoriser. Le
  code construisait à la volée 3 candidats (`"prenom nom"`,
  `"nom prenom"`, `nom seul`) à partir de `(last_norm, first_norm)`
  reparsés depuis `raw_author_name` côté Python — alors que
  `source_authorships.author_name_normalized` (peuplée à l'ingestion
  par la fonction SQL `normalize_name_form`) contient déjà cette forme
  normalisée, et que `compute_person_name_forms` génère toutes les
  variantes (ordres + initiales) au moment de la création de personne,
  variantes qui finissent dans `person_name_forms`. Donc lookup direct
  par `author_name_normalized` matche par construction.

  Effets de bord assumés :
  - Drop du fallback « nom seul » (matchait sur le seul nom de famille
    quand prénom absent — créait des faux positifs en pelle pour les
    homonymes).
  - Le code reste fonctionnellement plus strict mais sémantiquement
    identique pour les cas légitimes (les deux ordres `"fn ln"` et
    `"ln fn"` sont déjà dans `person_name_forms` côté création).

  Cache en mémoire des authorships créées au sein du run préservé
  (insertion des deux ordres) — utile pour matcher dans le même run
  une autre authorship de la personne qu'on vient de créer avec
  l'ordre inverse.

  L'item est **retiré de l'inventaire** plutôt que rapatrié — c'était
  une mauvaise modélisation initiale.
- **`domain/persons/matching.py` ouvert + `decide_match_by_identifier`** :
  factorisation des 2 clones IdRef/ORCID dans `step1b_idref` et
  `step2_orcid` de `create_persons_from_source_authorships.py`. Pattern
  identique « si la valeur est présente dans la map identifiant →
  person_id, rattacher » mutualisé en une fonction pure générique
  (marche pour n'importe quel id_type indexé sur `person_identifiers`).
  Module pensé pour accueillir progressivement la cascade contractuelle
  hal_account → cross_source → idref → orcid → name_forms.
- **`should_create_source_person` ajoutée à `domain/persons/creation.py`** :
  factorisation de l'invariant dupliqué 3 fois (HAL `upsert_hal_author`,
  ScanR `upsert_scanr_author`, theses `upsert_source_author`) « ne créer
  `source_persons` que si un identifiant fort est attaché ». Encapsule
  la nuance HAL (rejet explicite des `hal_person_id <= 0` qui sont des
  sentinelles internes) — les autres sources se contentent d'une
  vérification truthy. Sans identifiant fort, l'authorship reste
  exploitable via `raw_author_name + author_position` côté
  `source_authorships`.
- **`domain/persons/creation.py` ouvert + `allow_person_creation` rapatriée** :
  la règle « les rôles non-auteur des thèses (directeurs, rapporteurs,
  jury) n'autorisent pas la création d'une personne » descend dans
  `domain/persons/creation.py`. Le matching à une personne existante
  reste autorisé — c'est uniquement la décision « créer si pas de
  match » qui est filtrée. Module pensé pour s'étendre aux autres
  invariants de création (notamment `should_create_source_person`
  unifié HAL/ScanR/theses, dupliqué 3 fois aujourd'hui dans les
  normalizers). Distincte de la règle `OUT_OF_SCOPE_DOC_TYPES`
  (publications.scope) qui exclut entièrement memoir/peer_review du
  pipeline persons.
- **`domain/publications/` ouvert + scope.py expliciter la règle SQL
  implicite** : la vue SQL `v_active_publications` cachait la règle
  « doc_types out-of-scope » (peer_review, memoir : pas de matching
  person, pas d'authorship canonique, invisibles dans listings/stats)
  sans la documenter. Création de `domain/publications/scope.py` :
  `OUT_OF_SCOPE_DOC_TYPES` (frozenset) + `OUT_OF_SCOPE_DOC_TYPES_SQL`
  (forme SQL pour `NOT IN`). Refactor des 6 sites SQL qui hardcodaient
  la liste. La vue elle-même reste figée dans la migration (Postgres
  ne peut pas importer Python), mais un test d'intégration
  (`tests/integration/infrastructure/db/test_active_publications_view.py`)
  parse `pg_views` et garantit que la vue reflète bien la constante
  Python — garde-fou contre la divergence silencieuse. Pour les 2 sites
  qui étendent avec `ongoing_thesis` (stats de contribution effective),
  construction locale documentée à partir de `OUT_OF_SCOPE_DOC_TYPES`.
  Aucun changement comportemental — uniquement de l'explicitation.
- **`domain/persons/` ouvert et `domain/person.py` scindé** : le
  fichier plat à la racine est éclaté en trois sous-modules thématiques
  (cf. décision n°1 du chantier — granularité = dossier).
  - `domain/persons/identifiers.py` : VOs `ORCID`, `IdHAL`, `IdRef` +
    helper public `normalize_orcid` (les `_normalize_idhal` /
    `_normalize_idref` restent privés tant qu'aucun call site externe
    n'en a besoin).
  - `domain/persons/source_ids.py` : modèle Pydantic `PersonSourceIds`
    de la colonne JSONB `source_persons.source_ids`. Stand-alone : c'est
    un schéma de données, pas un identifiant — mélanger avec les VOs
    masquerait la nature.
  - `domain/persons/merge.py` : `check_can_merge_persons` (refus de
    fusion si deux fiches RH distinctes). Module pensé pour s'étendre
    aux règles de matching/déduplication/création quand on rapatriera
    les items inventaire correspondants.
  - 7 call sites mis à jour : `from domain.person import …` →
    `from domain.persons.<sous-module> import …`.
  - Tests scindés en miroir : `tests/unit/domain/persons/test_identifiers.py`,
    `test_source_ids.py`, `test_merge.py`.
  - Cleanup d'inventaire au passage : item HAL `parse_tei_author_identifiers`
    retiré (règle technique de parsing XML, mieux conservée à côté de
    la marche TEI qui la consomme — symétrique à `_hal_source_id`,
    `detected_countries`, `_parse_date_iso` déjà classés « limite »).
- **Découpage `last_name`/`first_name` — colonnes supprimées** :
  les colonnes `source_persons.last_name` et
  `source_persons.first_name` sont droppées (migration 022). Le
  parsing du nom est désormais fait à la lecture par
  `domain.names.parse_raw_author_name(raw_author_name)`,
  uniformément pour toutes les sources (auparavant : asymétrie
  HAL/ScanR/theses lisaient les colonnes, OA/WoS/Crossref parsaient
  déjà). Effets de bord : suppression des splits inlinés HAL et
  ScanR ; fusion de `fetch_linked_authorships_structured` +
  `fetch_linked_authorships_openalex` en une seule
  `fetch_linked_authorships` (l'asymétrie disparaît) ;
  `fetch_thesis_primary_author` réécrite pour lire
  `source_authorships.raw_author_name` ; suppression de la
  constante `SOURCES_WITH_STRUCTURED_NAMES` (plus de sens).
  Bonus : la règle « Nom, Prénom » (avec virgule) est désormais
  correctement parsée pour HAL/ScanR/theses — leur split inline
  ne la gérait pas.

## Décisions actées

1. **Granularité = dossier `domain/publications/` plutôt que fichiers
   plats à la racine de `domain/`**. Une fois qu'on aura ajouté
   `dedup.py`, `merge.py`, `rules.py` (règles suspects), `doi_conflict.py`
   et qu'on aura scindé l'actuel `publication.py` (VOs vs Pydantic
   biblio/meta vs topics), on aura ~6-7 fichiers : la lisibilité
   s'effondre à plat. Le dossier offre un préfixe d'import explicite
   (`from domain.publications.dedup import …`) qui rend le rôle de
   chaque module immédiat à la lecture, et permet d'évoluer (sous-
   modules `domain/persons/`, `domain/structures/`) sans refactor
   plus tard. Coût : un `__init__.py` par dossier, c'est négligeable.
2. **Reclassement one-shot des cas existants** en fin de chantier.
   SQL aligné sur la nouvelle règle, suivi d'une passe de vérification
   au prochain run pipeline pour s'assurer que la cascade en `domain/`
   produirait le même résultat.
4. **Détection figshare/Zenodo : hardcoded au démarrage, via
   `doi_prefixes` quand le chantier doi-ra-datacite aura abouti**.
   On démarre avec des helpers `is_figshare_doi`/`is_zenodo_doi` à
   préfixe en dur (suffisant pour les patterns connus). Si après
   doi-ra-datacite on constate que `doi_prefixes` couvre l'intégralité
   des cas réels, on migrera entièrement et on retirera les helpers
   préfixe. Pas de double path à maintenir intentionnellement — la
   migration est un objectif, pas un fallback permanent.

## Open questions (à examiner pendant ou après le chantier)

3. **Suppléments orphelins** (145 cas figshare au 2026-05-05 dont le
   parent n'est pas en BDD) : à sonder au cas par cas en fin de
   chantier. Hypothèses à tester : (a) parent présent avec un titre
   légèrement différent (matching à raffiner), (b) parent réellement
   absent et c'est correct (publi non-UCA), (c) parent réellement
   absent à tort (à retrouver). Cette question rejoint un futur
   chantier de modélisation des **relations entre publications**
   (parent ↔ supplément, ouvrage ↔ chapitre, version ↔ révision,
   …) — à n'ouvrir qu'une fois ce chantier-ci abouti.
5. **Matching par co-publication** : maintien, restriction (seuil
   max d'auteurs), ou suppression. À mesurer pendant la phase 3
   (rapatriement person matching) — quantifier le ratio matchings
   utiles / faux positifs sur les cas méga-paper avant d'arbitrer.
6. **ORCID OpenAlex/WoS sources fautives** : à mesurer pendant le
   rapatriement. Si le bruit dépasse le signal, on les sortira de
   la cascade et la décision se limitera à : ORCID Crossref →
   compte HAL → idref → nom.

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
