# Chantier — Déduplication & fusion de publications

Rassemblement préalable des éléments. Structure (contexte, décisions,
phasage) à formaliser au démarrage du chantier.

## Périmètre

Le pipeline contient aujourd'hui **6 cascades de matching/fusion**
disséminées qui font la même chose à chaque source ou presque, plus
des règles de fusion multi-source dupliquées entre `refresh_from_sources`
et les phases dédiées de fusion. Chantier coordonné nécessaire — toucher
l'un sans les autres laisse un état incohérent.

Deux dimensions imbriquées :

- **Refactorisation** : extraire les décisions pures vers
  `domain/publications/dedup.py` et `domain/publications/merge.py`,
  unifier les sites qui font la même chose.
- **Changement de logique** : la règle « choix de la publication cible
  de fusion » est arbitraire (les métadonnées canoniques sont triangulées
  par `refresh_from_sources` après fusion) — simplifier cette règle
  partout, supprimer le ranking SQL, gérer correctement les redirections
  en chaîne.

## Items concernés

### Cascades de matching dispersées (5 sites, 5 variantes)

#### `find_or_create — cascade de déduplication`
- **localisation** : `application/publications.py:128-197`
- **description** : Cascade DOI → NNT → création (avec gestion de
  conflit DOI déléguée à `resolve_doi_conflict`). Enchaîne aussi le
  `try_merge_by_doi` quand une thèse trouvée par NNT n'a pas de DOI
  alors qu'on en propose un.
- **prefetch** : `doi_match`, `nnt_match`.
- **destination** : `domain/publications/dedup.py` →
  `decide_publication_match(*, doi_match, nnt_match) -> PublicationMatchDecision`.

#### `try_merge_by_doi`
- **localisation** : `application/publications.py:76-96`
- **description** : Si la pub courante n'a pas de DOI mais qu'un DOI
  candidat est fourni, et qu'une autre pub porte ce DOI → fusion ;
  sinon attribution. Mini-règle de dédup tardive.
- **destination** : `domain/publications/dedup.py` →
  `decide_doi_attribution(current_doi, proposed_doi, existing_match) -> DoiAttributionDecision`.

#### `find_publication — cascade priorisée HAL > NNT > openalex_id > title` (OpenAlex)
- **localisation** : `application/pipeline/normalize/normalize_openalex.py:604-618`
- **description** : (1) HAL location → `find_hal_publication_id`,
  (2) theses.fr → `find_by_nnt`, (3) `openalex_id`, (4) DOI/title via
  `find_or_create(allow_create=False)`.
- **destination** : `domain/publications/dedup.py` →
  `decide_openalex_pub_match(*, hal_match, nnt_match, openalex_id_match, title_doi_match) -> PublicationMatchDecision`.

#### `find_publication theses — cascade DOI/NNT puis title+author`
- **localisation** : `application/pipeline/normalize/normalize_theses.py:122-172`
- **description** : Cascade DOI/NNT (via `find_or_create`), puis dédup
  spéciale par titre+année + compatibilité auteur (`thesis_authors_compatible`
  déjà en domain). Plus `try_merge_by_doi` quand match par titre + DOI
  candidat.
- **destination** : `domain/publications/dedup.py` →
  `decide_thesis_match(*, doi_nnt_match, title_year_candidates, claimed_author) -> PublicationMatchDecision`.

#### `process_work — fusion HAL deux pubs (DOI/NNT)`
- **localisation** : `application/pipeline/normalize/normalize_hal.py:681-693`
- **description** : Si le `hal_id` pointait sur `old_pub_id` mais
  `find_publication` (DOI/NNT) trouve `publication_id` différent →
  fusion auto. Invariant « un hal_id ne pointe qu'une publication ».
- **destination** : `domain/publications/dedup.py` →
  `decide_hal_id_repointing(old_pub_id, new_pub_id) -> RepointDecision`.

### Règles de fusion multi-source

#### `refresh_from_sources — règles de fusion`
- **localisation** : `application/publications.py:297-383` (orchestration),
  avec règles inlinées dans `_first_non_null` (220-225), `_merge_lists`
  (228-237), `_merge_jsonb` (240-249), `_topics_by_source` (252-259),
  `_first_doc_type` (262-294).
- **description** : Algo complet de canonicalisation multi-source : tri
  `SOURCE_PRIORITY`, scalaire = premier non-null prioritaire, OA =
  `best_oa_status` (déjà domain), retracted = OR logique, listes =
  union, JSONB shallow merge, topics composite par source, doc_type
  avec arbitrage sous-type. Plus auto-fusion DOI si collision (lookup
  + merge).
- **destination** : `domain/publications/merge.py` →
  `merge_source_rows(rows, *, source_priority) -> MergedPubFields` ;
  `decide_premerge_for_doi(new_doi, existing_match, current_pub_id) -> PreMergeDecision` ;
  helpers internes `first_non_null`, `merge_lists_dedup_ci`,
  `shallow_merge_jsonb`, `topics_by_source`,
  `arbitrate_doc_type_with_article_subtype`.

### Choix de la publication cible de fusion (4 sites, 4 règles ad hoc)

**Constat métier** : le choix de la cible **n'a aucun impact métier**
— les métadonnées canoniques sont triangulées par
`refresh_from_sources` selon `SOURCE_PRIORITY` après chaque fusion.
N'importe quelle publi peut survivre, du moment que le refresh est
appelé ensuite. Vaut pour les fusions par DOI, NNT, hal_id, etc.

État actuel — 4 règles ad hoc pour rien :

- `merge_pubs_by_hal_id` : « HAL gagne » (ordre des arguments fixé
  dans `_merge_pub(cur, hal_pub_id, src_pub_id, ...)`).
- `merge_pubs_by_nnt` : ranking SQL `rank_publications_by_merge_priority`
  (DOI shape + complétude + id ASC).
- `try_merge_by_doi` (`application/publications.py`) : sa propre
  cascade.
- `process_work` HAL (`normalize_hal.py:681-693`) : si `old_pub_id`
  rattaché au `hal_id` diffère de la publi trouvée par DOI/NNT,
  fusion `old → new` (la nouvelle DOI/NNT survit).

### Préalable [fait] : `refresh_from_sources(target)` après chaque fusion

Les 3 sites batch sont désormais homogènes côté refresh post-fusion :

- `try_merge_by_doi` : ✅ refresh implicite via `process_work` du
  normalizer en fin de traitement.
- `merge_pubs_by_hal_id` : ✅ refresh ajouté dans le savepoint après
  `_merge_pub` (commit `ce5cf4f`).
- `merge_pubs_by_nnt` : ✅ idem.

Bug latent fixé : avant ce changement, après une fusion via les phases
dédiées, les métadonnées canoniques de la cible restaient figées sur
ce qu'elles étaient avant absorption. L'existence de
`interfaces/cli/refresh_publications_year_mismatch.py` témoignait du
symptôme.

### Sous-point connexe : `refresh_from_sources` ignore `title`

`refresh_from_sources` ne touche pas à `title` / `title_normalized`
(cf. docstring l. 330). Si la cible a un mauvais titre et la publi
absorbée avait un meilleur titre, le titre canonique reste celui de
la cible. Limitation orthogonale à la fusion mais à signaler.

## Plan de chantier (résumé)

1. ✅ Ajouter `refresh_from_sources(target)` à la fin de chaque
   fusion dans les phases dédiées (`merge_pubs_by_hal_id`,
   `merge_pubs_by_nnt`).
2. ⏳ Remplacer `rank_publications_by_merge_priority` par un choix
   trivial (`min(pub_ids)` par exemple) appelé partout — suppression
   de la query SQL, du port, des tests dédiés.
3. ⏳ Conserver le **résolveur de chaîne** (présent dans
   `merge_pubs_by_hal_id`, absent dans `merge_pubs_by_nnt`) pour
   suivre les redirections accumulées dans le batch
   (`pub_A → pub_B` puis `pub_X → pub_A`). Le porter dans le helper
   unifié.
4. ⏳ Unifier les 4 sites en un seul appel à un helper commun
   `merge_publications_by_key(...)`.
5. ⏳ Migrer les 5 cascades de matching vers `domain/publications/dedup.py`
   en factorisant — `decide_publication_match` paramétré par les
   lookups disponibles plutôt qu'une fonction par source.

## Identifiants de déduplication (à formaliser comme donnée métier)

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
    # DedupIdentifier("pmid", priority=4),  # le jour où on en aura
)
```

Exceptions concrètes à formaliser :

- **DOI chapitre vs ouvrage** : un même DOI peut identifier un
  chapitre (`book_chapter`) ET l'ouvrage entier (`book`) chez certains
  éditeurs. Pas de fusion automatique entre les deux.
- **DOI dataset vs article** (cf. trigger figshare) : un DOI Zenodo/
  figshare peut être lié à un article par `relatedIdentifier` mais
  n'EST pas l'article. Pas de match par DOI dans ce sens.
- **NNT vs DOI** : la priorité actuelle (DOI > NNT) suppose que quand
  deux thèses partagent un NNT mais ont des DOI différents, elles
  sont distinctes. À documenter explicitement.

## Signatures principales suggérées

```python
# domain/publications/dedup.py
@dataclass(frozen=True)
class PublicationMatchDecision:
    action: Literal["match", "create"]
    publication_id: int | None = None
    reason: str = ""  # 'doi' | 'nnt' | 'title_year' | …

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

def decide_hal_id_repointing(
    old_pub_id: int | None, new_pub_id: int | None,
) -> RepointDecision: ...

# domain/publications/merge.py
def merge_source_rows(
    rows: list[SourcePubRow], *, source_priority: tuple[str, ...],
) -> MergedPubFields: ...

def resolve_merge_redirect(pub_id: int, redirects: Mapping[int, int]) -> int: ...
# Helpers internes : first_non_null, merge_lists_dedup_ci,
# shallow_merge_jsonb, topics_by_source,
# arbitrate_doc_type_with_article_subtype
```

## Liens

- Fix préalable étape 1 : commit `ce5cf4f`
- Pattern de référence (décision pure déjà en domain) :
  [`resolve_doi_conflict`](../../domain/publication.py#L562)
