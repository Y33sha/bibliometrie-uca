# Inventaire des règles métier — phase 0

Livrable de la phase 0 du chantier
[regles-metier-domain.md](docs/chantiers/regles-metier-domain.md). Liste
toutes les règles métier (≠ orchestration) repérées dans les fichiers
de pipeline et les services applicatifs, classées :

- **(a) déjà pure** : relocalisable telle quelle dans `domain/`
- **(b) décomposable** : décision pure + effets séparables, prefetch
  identifié
- **(c) intrinsèque transaction** : pas de décision à isoler, reste en
  `application/`

Pour chaque règle : localisation, description courte, classification,
destination `domain/` proposée (module + nom de fonction).

Périmètre : `application/persons.py`, `application/publications.py`,
les six normalizers `application/pipeline/normalize/*.py` + leurs
helpers, les fichiers `pipeline/persons/`, `pipeline/publications/` et
`pipeline/authorships/`.

---

## `application/publications.py`

### find_or_create — cascade de déduplication
- **localisation** : `application/publications.py:128-197`
- **description** : Cascade DOI → NNT → création (avec gestion de
  conflit DOI déléguée à `resolve_doi_conflict`). Enchaîne aussi le
  `try_merge_by_doi` quand une thèse trouvée par NNT n'a pas de DOI
  alors qu'on en propose un.
- **classification** : (b) — décision « match doi vs match nnt vs
  create » pure si on lui passe les résultats de `find_by_doi` et
  `find_by_nnt`. Prefetch : `doi_match`, `nnt_match`.
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_publication_match(*, doi_match, nnt_match) -> PublicationMatchDecision`.

### try_merge_by_doi
- **localisation** : `application/publications.py:76-96`
- **description** : Si la pub courante n'a pas de DOI mais qu'un DOI
  candidat est fourni, et qu'une autre pub porte ce DOI → fusion ;
  sinon attribution. Mini-règle de dédup tardive.
- **classification** : (b) — décision pure si on lui passe
  `current_doi`, `proposed_doi`, `existing_match: PubByDoi | None`.
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_doi_attribution(current_doi, proposed_doi, existing_match) -> DoiAttributionDecision`.

### refresh_from_sources — règles de fusion
- **localisation** : `application/publications.py:297-383` (orchestration),
  avec règles inlinées dans :
  - `_first_non_null` (220-225) : « premier non-null dans l'ordre
    `SOURCE_PRIORITY` ». Pure.
  - `_merge_lists` (228-237) : union dédupliquée case-insensitive de
    listes. Pure.
  - `_merge_jsonb` (240-249) : merge shallow par clé, première clé
    rencontrée gagne. Pure.
  - `_topics_by_source` (252-259) : indexe les topics par source dans
    un dict composite. Pure.
  - `_first_doc_type` (262-294) : règle « sous-type d'article prime
    sur `article` générique » (CrossRef dit `journal-article`, HAL dit
    `art_artrev` → on garde `review`). Pure (utilise `map_doc_type` +
    `ARTICLE_SUBTYPES`).
- **description** : Algo complet de canonicalisation multi-source : tri
  `SOURCE_PRIORITY`, scalaire = premier non-null prioritaire, OA =
  `best_oa_status` (déjà domain), retracted = OR logique, listes =
  union, JSONB shallow merge, topics composite par source, doc_type
  avec arbitrage sous-type. Plus auto-fusion DOI si collision (lookup
  + merge).
- **classification** : (b) — toute la décision « rows → MergedPubFields »
  est pure si on lui passe la liste de rows triée. SELECT et UPDATE
  restent en application. La règle d'auto-fusion DOI est elle-même
  décomposable.
- **destination domain/** : `domain/publications/merge.py` →
  `merge_source_rows(rows, *, source_priority) -> MergedPubFields` ;
  `decide_premerge_for_doi(new_doi, existing_match, current_pub_id) -> PreMergeDecision` ;
  helpers internes `first_non_null`, `merge_lists_dedup_ci`,
  `shallow_merge_jsonb`, `topics_by_source`,
  `arbitrate_doc_type_with_article_subtype`.

---

## `application/pipeline/normalize/normalize_hal.py`

---

## `application/pipeline/normalize/normalize_openalex.py`

### find_publication — cascade priorisée HAL > NNT > openalex_id > title
- **localisation** : `application/pipeline/normalize/normalize_openalex.py:604-618`
- **description** : (1) si HAL location → `find_hal_publication_id`,
  (2) si theses.fr → `find_by_nnt`, (3) sinon `openalex_id`,
  (4) sinon DOI/title via `find_or_create(allow_create=False)`.
- **classification** : (b) — pure si on lui passe les 4 lookups.
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_openalex_pub_match(*, hal_match, nnt_match, openalex_id_match, title_doi_match) -> PublicationMatchDecision`.

---

## `application/pipeline/normalize/normalize_theses.py`

### find_publication theses — cascade DOI/NNT puis title+author
- **localisation** : `application/pipeline/normalize/normalize_theses.py:122-172`
- **description** : Cascade : DOI/NNT (via find_or_create), puis
  dédup spéciale par titre+année + compatibilité auteur. Plus
  `try_merge_by_doi` quand match par titre + DOI candidat.
- **classification** : (b).
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_thesis_match(*, doi_nnt_match, title_year_candidates, claimed_author) -> PublicationMatchDecision`.

---

## `application/pipeline/persons/create_persons_from_source_authorships.py`

### contrat de la cascade globale
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:1-33` (docstring) + `:389-420` (orchestrateur)
- **description** : Hiérarchie de fiabilité (compte HAL > cross-source
  > IdRef > ORCID > nom), aujourd'hui dispersée. **Correspond à
  `decide_person_match` du chantier**.
- **classification** : (b) — prefetch des 5 résultats des étapes.
- **destination domain/** : `domain/persons/matching.py` →
  `decide_person_match(*, hal_account_match, cross_source_match, idref_match, orcid_match, name_form_outcome) -> PersonMatchDecision`.

---

## Synthèse globale

### Comptage par classification

| Classification | Périmètre 1<br>(normalize/* + persons.py + publications.py) | Périmètre 2<br>(pipeline/persons + pipeline/publications + pipeline/authorships) | **Total** |
|---|---:|---:|---:|
| **(a) déjà pure** | 0 | 0 | **0** |
| **(b) décomposable** | 5 | 1 | **6** |
| **(c) intrinsèque transaction** | 0 | 0 | **0** |
| **Total** | 5 | 1 | **6** |

### Patterns dupliqués majeurs

5. **Règle `doc_type theses` (`thesis` vs `ongoing_thesis`)** —
   dupliquée dans `normalize_theses.py:88` et `:247`. À unifier dans
   `domain/doc_types.theses_doc_type` (mentionné dans le doc chantier).

6. **Cascade de matching publication multi-source** (DOI/NNT/title/source-id)
   — implémentée 5 fois, une par source : HAL, OpenAlex, WoS, ScanR,
   theses, Crossref. Toutes variantes de `decide_publication_match`.
   À unifier dans `domain/publications/dedup.py`.

8. **Choix de canonicité par source** — la règle « HAL gagne en cas
   de doublon » (`merge_pubs_by_hal_id`) et le ranking NNT
   (`merge_pubs_by_nnt`) sont deux instances d'une même fonction
   `pick_canonical_by_source_priority` paramétrable. À factoriser dans
   `domain/publications/merge.py`.

### Nouveaux modules `domain/` à créer

```
domain/publications/
├── __init__.py
├── dedup.py           # cascade de matching, conflits DOI, classify_hal_id_duplicates
├── merge.py           # règles de fusion multi-source (refresh_from_sources, ranking)
├── oa.py              # mappings et arbitrage OA par source
├── theses.py          # règles spécifiques aux thèses (year, author compat, doc_type)
└── external_ids.py    # extract_external_ids_from_urls

domain/persons/
├── __init__.py
├── identifiers.py     # ORCID/idref/idhal : normalisation, dispatch par source
├── sourcing.py        # invariants source_persons par source, name_forms
└── matching.py        # decide_person_match, decide_match_by_identifier, …

domain/sources/
├── __init__.py
├── openalex_signals.py   # is_theses_fr, is_hal_primary_location, is_repository, NNT, etc.
├── scanr_signals.py      # select_leaf_affiliations, NNT depuis scanr_id
├── crossref_signals.py   # pub_year cascade, ISSNs, JATS strip, meta whitelist
├── wos_signals.py        # is_author_exploitable
└── hal_signals.py        # pick_structure_field
```

À enrichir dans `domain/doc_types.py` :

- `theses_doc_type(date_soutenance) -> str`
- `map_hal_doc_type_with_subtype(raw_type, raw_sub) -> str`
- `override_doc_type_from_signals(...)` (signature dans doc chantier)

### Signatures principales suggérées

```python
# domain/publications/dedup.py
def decide_publication_match(
    *, doi_match: PubByDoi | None,
    nnt_match: PubByNnt | None,
    source_id_match: int | None = None,
    title_year_match: PubByTitle | None = None,
) -> PublicationMatchDecision: ...

def decide_doi_attribution(
    current_doi: str | None,
    proposed_doi: str | None,
    existing_match: PubByDoi | None,
) -> DoiAttributionDecision: ...

def classify_hal_id_duplicates(
    hal_rows: list[HalPubRow],
    other_source_rows: list[OtherSourcePubRow],
) -> tuple[list[LinkAction], list[MergeAction]]: ...

def has_minimal_publication_metadata(title: str | None, pub_year: int | None) -> bool: ...

# domain/publications/merge.py
def merge_source_rows(
    rows: list[SourcePubRow], *, source_priority: tuple[str, ...],
) -> MergedPubFields: ...

def pick_canonical_publication_by_source_priority(
    target_source_priority: list[str],
    candidates: list[tuple[int, str]],
) -> int: ...

def rank_publications_by_merge_priority(pubs: list[PubMergeCandidate]) -> list[int]: ...

def resolve_merge_redirect(pub_id: int, redirects: Mapping[int, int]) -> int: ...

# Règles OA migrées source par source dans domain/sources/{hal,scanr,openalex,wos}.py
# Pas de domain/publications/oa.py créé (la mutualisation envisagée
# ne s'est pas matérialisée — sémantiques sources distinctes).
# Constante de fallback canonique :
#   domain.publication.OA_STATUS_UNKNOWN_DEFAULT = "unknown"

# domain/publications/theses.py
def theses_doc_type(date_soutenance: str | None) -> str: ...
def thesis_authors_compatible(candidate, claimed) -> bool: ...
def aggregate_thesis_persons(these: dict) -> list[ThesisAuthorship]: ...

# domain/persons/identifiers.py
def iter_identifier_writes(authorships) -> Iterable[IdentifierWrite]: ...
def pick_idhal_from_tei_idnos(idnos: list) -> dict[str, str]: ...

# domain/persons/sourcing.py
def should_create_source_person(source: str, *, strong_id) -> bool: ...
def allow_person_creation_from_authorship(source: str, roles: list[str]) -> bool: ...
def merge_name_form_provenance(existing, additional_pid, additional_source) -> NameFormEntry: ...
def can_delete_obsolete_name_form(sources: set[str]) -> bool: ...
def aggregate_authorship_perimeter(source_rows) -> tuple[bool, list[int]]: ...
def should_reset_before_propagation(active_sources: set[str], all_sources: set[str]) -> bool: ...

# domain/persons/matching.py
def decide_person_match(
    *, hal_account_match, cross_source_match,
    idref_match, orcid_match, name_form_outcome,
) -> PersonMatchDecision: ...

def decide_cross_source_match(
    authorship_source, last_norm, first_norm, candidates,
) -> int | None: ...

def decide_match_by_identifier(
    value: str | None, identifier_map: Mapping[str, int],
) -> int | None: ...

def lookup_name_forms(
    last_norm, first_norm, name_form_map,
) -> list[int] | None: ...

def decide_name_form_outcome(
    person_ids: list[int] | None, allow_create: bool,
) -> NameFormDecision: ...

# domain/sources/openalex_signals.py
def is_theses_fr_source(work: dict) -> bool: ...
def is_hal_primary_location(work: dict) -> bool: ...
def is_repository_source(work: dict) -> bool: ...
def should_skip_publisher_journal(work: dict) -> bool: ...
def extract_nnt_from_openalex(work: dict) -> str | None: ...
def keep_orcid_if_name_matches(raw_full_name, oa_full_name, oa_orcid) -> str | None: ...

# domain/sources/scanr_signals.py
def select_leaf_affiliations(affiliations: list[dict]) -> list[dict]: ...

# domain/sources/crossref_signals.py
def extract_crossref_pub_year(msg: dict, *, max_year: int) -> int | None: ...
def parse_crossref_issns(msg: dict) -> tuple[str | None, str | None]: ...
def strip_jats_tags(s: str) -> str: ...
def extract_crossref_meta(msg: dict) -> dict | None: ...

# domain/sources/hal_signals.py
def pick_hal_structure_field(doc: dict) -> Literal["primary", "flat"]: ...

# domain/publications/external_ids.py
def extract_external_ids_from_urls(urls: list[str]) -> dict[str, str]: ...
```

### Notes hors périmètre

- `domain/authorship_roles.map_role` et `THESES_FIELD_ROLES` couvrent
  déjà proprement le mapping rôles. Pas de duplication détectée dans
  les normalizers.
- `domain/zenodo.is_zenodo_doi` est utilisé par HAL et OpenAlex pour
  skip les concept DOIs Zenodo. La résolution
  (`zenodo_resolver.resolve`) reste un effet (port `ZenodoResolver`).
- L'invariant `check_can_merge_persons` dans `domain/person.py` est le
  pattern de référence à reproduire pour les autres règles
  décisionnelles (déjà cité dans le doc chantier aux côtés de
  `resolve_doi_conflict`).
