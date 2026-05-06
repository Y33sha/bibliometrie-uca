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

## `application/persons.py`

### add_identifiers_from_authorships
- **localisation** : `application/persons.py:250-265`
- **description** : Règle de provenance idref — quand on ingère un
  identifiant idref depuis un groupe d'authorships, la `source`
  enregistrée sur `person_identifiers` est celle de l'authorship qui le
  porte (défaut `"hal"`). L'ORCID et l'idHAL n'ont pas cette logique
  de provenance variable. Déduplique aussi les couples
  `(id_type, id_value)` à l'intérieur du lot.
- **classification** : (b) — décision « quels (type, value, source)
  émettre depuis une liste d'authorships, sans doublon » est pure ;
  les `add_identifier(...)` qui suivent sont des effets.
- **destination domain/** : `domain/persons/identifiers.py` →
  `iter_identifier_writes(authorships) -> Iterable[IdentifierWrite]`

### merge_person / async_merge_person — invariant RH
- **localisation** : `application/persons.py:452-463` + `:466-472`
- **description** : Refus de fusion entre deux `persons` ayant chacune
  une fiche RH distincte (perte d'info humaine). Invariant déjà
  déporté dans `domain/person.check_can_merge_persons` qui prend le
  booléen `has_distinct_rh` en argument.
- **classification** : (a) — décision pure dans `domain/person.py`,
  fonction application orchestre SELECT + UPDATE + audit.
- **destination domain/** : n/a (déjà fait, modèle de référence).

### _SOURCE_CONFIG (mapping ORCID/idref/idhal par source)
- **localisation** : `application/persons.py:313-344`
- **description** : Table par source : pour chaque source, quels
  identifiants sont attachables (`orcid`, `idref`), quels champs de
  `source_ids` (`idhal` côté HAL). Encodage de la fiabilité par
  source — HAL a `idhal`, ScanR/theses ont `idref`,
  OpenAlex/WoS/Crossref n'ont qu'ORCID.
- **classification** : (a) — constante module-level pure mais
  mal localisée.
- **destination domain/** : `domain/persons/identifiers.py` → constante
  `IDENTIFIER_FIELDS_BY_SOURCE`.

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

### resolve_doi_conflict (orchestration)
- **localisation** : `application/publications.py:99-125`
- **description** : Orchestrateur : appelle la règle pure
  `domain.publication.resolve_doi_conflict` puis applique l'effet
  `clear_doi`.
- **classification** : (a) — décision déjà pure.
- **destination domain/** : n/a (modèle de référence).

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

### merge_publications (orchestration)
- **localisation** : `application/publications.py:405-423`
- **description** : Séquence : repo.merge_into → repo.update_sources →
  emit_event. Pas de décision.
- **classification** : (c).
- **destination domain/** : n/a.

---

## `application/pipeline/normalize/normalize_hal.py`

### parse_tei_author_identifiers — règle idHAL string vs numeric
- **localisation** : `application/pipeline/normalize/normalize_hal.py:285-334` (cœur l. 324-332)
- **description** : Le TEI HAL produit deux `<idno type="idhal">` par
  auteur (un slug `string`, un id numérique). On ne garde que le slug
  `string`. Le numérique est en réalité le `hal_person_id` ré-étiqueté.
- **classification** : (a) — pure mais embarquée dans un parsing XML.
  Décomposable parser XML (sans règle) + sélecteur (avec règle).
- **destination domain/** : `domain/persons/identifiers.py` →
  `pick_idhal_from_tei_idnos(idnos) -> dict[str, str]`.

### _hal_source_id — convention de clé HAL
- **localisation** : `application/pipeline/normalize/normalize_hal.py:337-350`
- **description** : `source_id` côté HAL = `hal_person_id` si compte
  HAL, sinon `0_{form_id}`, sinon `nokey-{old_id}`.
- **classification** : (a).
- **destination domain/** : limite — convention de clé d'infra. À
  laisser en place ou `domain/persons/identifiers.py`.

### upsert_hal_author — invariant « source_persons HAL = compte HAL »
- **localisation** : `application/pipeline/normalize/normalize_hal.py:356-408` (cœur l. 374-377)
- **description** : Règle source_persons : on n'écrit que si
  `hal_person_id` fourni. Sinon `source_person_id=NULL` côté
  authorship et identifiants vivent sur `source_authorships.identifiers`.
- **classification** : (b) — décision booléenne pure étant donné
  `hal_person_id`.
- **destination domain/** : `domain/persons/sourcing.py` →
  `should_create_source_person(source, *, strong_id) -> bool` (unifié
  HAL/ScanR/theses).

### Mapping authQuality_s
- **localisation** : `application/pipeline/normalize/normalize_hal.py:584-586`
- **description** : `aut/crp/dir/edt` → roles + flag corresponding via
  `domain.authorship_roles.map_role`.
- **classification** : (a) — déjà domain.
- **destination domain/** : n/a.

### Découpage `last_name` / `first_name` HAL
- **localisation** : `application/pipeline/normalize/normalize_hal.py:383-389`
- **description** : « tout sauf le dernier token = first_name, dernier
  token = last_name ». Heuristique faible, dupliquée verbatim dans
  ScanR.
- **classification** : (a), dupliquée.
- **destination domain/** : `domain/names.py` →
  `split_full_name_naive(full_name) -> tuple[str | None, str]`.

### parse_author_structures — préférence primary > flat
- **localisation** : `application/pipeline/normalize/normalize_hal.py:416-486` (règle l. 437)
- **description** : Préférence `authIdHasPrimaryStructure_fs` (labos
  feuilles) sur `authIdHasStructure_fs` (arbre aplati incluant tutelles
  parentes). Évite la pollution `addresses` par les tutelles parentes.
- **classification** : (b) — choix de liste source = pure ; parsing
  TSV-like reste.
- **destination domain/** : `domain/sources/hal_signals.py` →
  `pick_hal_structure_field(doc) -> Literal["primary", "flat"]`.

### process_work — fusion HAL deux pubs (DOI/NNT)
- **localisation** : `application/pipeline/normalize/normalize_hal.py:713-723`
- **description** : Si le hal_id pointait sur `old_pub_id` mais
  `find_publication` (matche par DOI/NNT) trouve `publication_id`
  différent → fusion auto. Invariant « un hal_id ne peut pointer
  qu'un seul DOI/NNT ».
- **classification** : (b).
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_hal_id_repointing(old_pub_id, new_pub_id) -> RepointDecision`.

---

## `application/pipeline/normalize/normalize_openalex.py`

### extract_locations_data — extraction d'identifiants depuis URLs
- **localisation** : `application/pipeline/normalize/normalize_openalex.py:73-114`
- **description** : « Premier non-null parmi les URLs de locations,
  dans l'ordre listé ». Patterns regex pour HAL, NNT (theses.fr),
  PMID, PMC.
- **classification** : (b) — patterns + ordre = pure ; boucle reste
  parsing.
- **destination domain/** : `domain/publications/external_ids.py` →
  `extract_external_ids_from_urls(urls: list[str]) -> dict[str, str]`.

### find_publication — cascade priorisée HAL > NNT > openalex_id > title
- **localisation** : `application/pipeline/normalize/normalize_openalex.py:604-618`
- **description** : (1) si HAL location → `find_hal_publication_id`,
  (2) si theses.fr → `find_by_nnt`, (3) sinon `openalex_id`,
  (4) sinon DOI/title via `find_or_create(allow_create=False)`.
- **classification** : (b) — pure si on lui passe les 4 lookups.
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_openalex_pub_match(*, hal_match, nnt_match, openalex_id_match, title_doi_match) -> PublicationMatchDecision`.

### Conflit DOI au moment de l'enrichissement
- **localisation** : `application/pipeline/normalize/normalize_openalex.py:620-636`
- **description** : Si nouveau DOI X collisionne, délègue à
  `resolve_doi_conflict` (déjà domain) avec mémorisation du
  `source_doi` original sur `external_ids` quand le DOI a été retiré
  (chapitre vs ouvrage).
- **classification** : (a) — décision déjà pure ; reste la convention
  `source_doi`.
- **destination domain/** : à exposer comme effet retourné par
  `DoiConflictResolution.original_doi_to_preserve`.

---

## `application/pipeline/normalize/normalize_wos.py`

### authors_kept — filtre daisng_id
- **localisation** : `application/pipeline/normalize/normalize_wos.py:573-577`
- **description** : Skip auteurs sans `daisng_id` ni `full_name` (=
  parsing API douteux).
- **classification** : (a).
- **destination domain/** : `domain/sources/wos_signals.py` →
  `is_wos_author_exploitable(author) -> bool`.

### _build_wos_identifiers
- **localisation** : `application/pipeline/normalize/normalize_wos.py:508-515`
- **description** : Mapping dict identifiants WoS → JSONB normalisé
  `{orcid, researcher_id}`. None si rien. `daisng_id` n'est pas
  cross-source, ResearcherID l'est.
- **classification** : (a).
- **destination domain/** : `domain/persons/identifiers.py` →
  `build_authorship_identifiers_for_source(source, author_dict) -> dict | None`
  (dispatch par source, pattern dupliqué cf. synthèse).

---

## `application/pipeline/normalize/normalize_scanr.py`

### select_labo_affiliations — préférence labo sur tutelles
- **localisation** : `application/pipeline/normalize/normalize_scanr.py:50-60`
- **description** : Symétrique HAL `primary_structure` : ne garder
  que les affiliations labo (`id_name_author_labo` non vide), fallback
  sur la liste complète. ScanR aplatit les tutelles.
- **classification** : (a).
- **destination domain/** : `domain/sources/scanr_signals.py` →
  `select_leaf_affiliations(affiliations) -> list[dict]`.

### _extract_nnt_from_scanr_id
- **localisation** : `application/pipeline/normalize/normalize_scanr.py:103-106`
- **description** : `scanr_id` qui commence par `these` encode un NNT
  (ex. `these2021CLFAC030`).
- **classification** : (a).
- **destination domain/** : `domain/sources/scanr_signals.py` →
  `extract_nnt_from_scanr_id(scanr_id) -> str | None`.

### upsert_scanr_author — invariant « idref ou rien »
- **localisation** : `application/pipeline/normalize/normalize_scanr.py:254-286`
- **description** : Crée la `source_persons` que si `idref` (PPN)
  présent. Symétrique HAL et theses.
- **classification** : (b).
- **destination domain/** : `domain/persons/sourcing.py` →
  `should_create_source_person` (unifié).

### Découpage last_name/first_name (duplication)
- **localisation** : `application/pipeline/normalize/normalize_scanr.py:270-276`
- **description** : Heuristique identique à HAL.
- **classification** : (a), dupliquée.
- **destination domain/** : `domain/names.py` →
  `split_full_name_naive`.

### detected_countries — propagation
- **localisation** : `application/pipeline/normalize/normalize_scanr.py:330-339`
- **description** : Pour chaque affiliation ScanR, accumulation
  dédupliquée des `detected_countries` au niveau document. Premier vu,
  ordre préservé.
- **classification** : (a).
- **destination domain/** : `domain/sources/scanr_signals.py` →
  `collect_detected_countries(affiliations) -> list[str]` (limite :
  trivial, peut rester inline).

---

## `application/pipeline/normalize/normalize_theses.py`

### pub_year — fallback dateSoutenance > datePremiereInscription
- **localisation** : `application/pipeline/normalize/normalize_theses.py:90-102` (+ dupliqué `:249-261`)
- **description** : Année = soutenance, sinon première inscription.
  Pour thèses en cours, l'inscription fait foi.
- **classification** : (a), dupliquée.
- **destination domain/** : `domain/publications/theses.py` →
  `extract_thesis_year(date_soutenance, date_inscription) -> int | None`.

### _thesis_author_compatible — règle de matching auteur thèse
- **localisation** : `application/pipeline/normalize/normalize_theses.py:62-79`
- **description** : Pour matcher une thèse par titre+année, vérifier
  compatibilité auteur principal : (1) si auteur DB inconnu, accepter ;
  (2) sinon `names_compatible` ; (3) fallback « tokens identiques »
  pour les particules (Le, Da, Ben).
- **classification** : (b).
- **destination domain/** : `domain/publications/theses.py` →
  `thesis_authors_compatible(candidate, claimed) -> bool`.

### find_publication theses — cascade DOI/NNT puis title+author
- **localisation** : `application/pipeline/normalize/normalize_theses.py:122-172`
- **description** : Cascade : DOI/NNT (via find_or_create), puis
  dédup spéciale par titre+année + compatibilité auteur. Plus
  `try_merge_by_doi` quand match par titre + DOI candidat.
- **classification** : (b).
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_thesis_match(*, doi_nnt_match, title_year_candidates, claimed_author) -> PublicationMatchDecision`.

### upsert_source_author — invariant « PPN ou rien »
- **localisation** : `application/pipeline/normalize/normalize_theses.py:317-334`
- **description** : Comme HAL/ScanR, écrit `source_persons` que si
  PPN présent.
- **classification** : (b).
- **destination domain/** : `domain/persons/sourcing.py` →
  `should_create_source_person` (unifié).

### process_persons — agrégation rôles par personne
- **localisation** : `application/pipeline/normalize/normalize_theses.py:358-424`
- **description** : Une même personne peut apparaître dans plusieurs
  champs (auteur+jury, directeur+rapporteur). Regrouper par PPN, ou à
  défaut par `(nom, prenom)`, fusionner les rôles via `merge_roles`.
  Convention `position` incrémentée seulement pour les `author`. Plus
  convention « partenaires de recherche → addr_parts pour TOUTES les
  personnes du doc ».
- **classification** : (b).
- **destination domain/** : `domain/publications/theses.py` →
  `aggregate_thesis_persons(these: dict) -> list[ThesisAuthorship]`.

### _parse_date_iso JJ/MM/AAAA → YYYY-MM-DD
- **localisation** : `application/pipeline/normalize/normalize_theses.py:175-183`
- **description** : Conversion format theses.fr vers ISO.
- **classification** : (a).
- **destination domain/** : `domain/publications/theses.py` →
  `parse_theses_date_iso(s) -> str | None` (limite : peut rester
  inline).

### _build_source_meta
- **localisation** : `application/pipeline/normalize/normalize_theses.py:207-233`
- **description** : Construction du dict `meta` JSONB pour
  source_publications theses : dates, discipline, écoles doctorales,
  partenaires (filtré sur nom non vide).
- **classification** : (a).
- **destination domain/** : `domain/publications/theses.py` →
  `build_thesis_source_meta(these) -> dict | None` (limite : plus du
  parsing).

---

## `application/pipeline/normalize/normalize_crossref.py`

### get_pub_year — cascade published > issued > online > print + clamp
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:71-94`
- **description** : Année = première date valide dans
  `published > issued > published-online > published-print`, **borne
  supérieure year+1**, borne inférieure 1500. Un preprint daté de
  l'année prochaine reste plausible, au-dessus c'est pollué.
- **classification** : (a) (paramétrer `max_year` pour testabilité).
- **destination domain/** : `domain/sources/crossref_signals.py` →
  `extract_crossref_pub_year(msg, *, max_year) -> int | None`.

### get_issns — eissn vs print via issn-type
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:108-130`
- **description** : Si CrossRef expose `issn-type`, séparer par `type`
  (electronic vs print) ; sinon premier `ISSN`.
- **classification** : (a).
- **destination domain/** : `domain/sources/crossref_signals.py` →
  `parse_crossref_issns(msg) -> tuple[str | None, str | None]`.

### get_abstract — strip JATS XML
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:148-157`
- **description** : Abstract en JATS XML, retirer les tags.
- **classification** : (a).
- **destination domain/** : `domain/sources/crossref_signals.py` →
  `strip_jats_tags(s) -> str` (limite : helper text-cleaning
  générique possible).

### get_meta — sélection champs CrossRef à conserver
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:199-219`
- **description** : Liste blanche : `license`, `funder`, `relation`,
  `references_count` (si > 0), `indexed.timestamp`. Décision « ces
  champs ont une valeur, les autres on jette ».
- **classification** : (a).
- **destination domain/** : `domain/sources/crossref_signals.py` →
  `extract_crossref_meta(msg) -> dict | None`.

### authenticated-orcid : « stocker mais ne pas l'utiliser comme filtre »
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:331-332`
- **description** : Malgré le nom, ce flag CrossRef est non fiable (les
  éditeurs n'utilisent pas le workflow OAuth), on le stocke en
  `source_data` pour traçabilité mais on ne s'en sert PAS pour filtrer.
- **classification** : (a) (convention plus que calcul).
- **destination domain/** : à documenter en constante/note dans
  `domain/sources/crossref_signals.py`.

### Convention `source_id` Crossref = `<DOI>:<position>`
- **localisation** : `application/pipeline/normalize/normalize_crossref.py:13-19`
- **description** : Pas d'identifiant stable côté auteur Crossref →
  convention de génération.
- **classification** : (c) — supplantée par le fait qu'on n'écrit plus
  `source_persons` Crossref.
- **destination domain/** : n/a.

---

## `application/pipeline/persons/create_persons_from_source_authorships.py`

### filtre_orcid_openalex_par_compatibilité_de_nom
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:74-83`
- **description** : Conserve un ORCID OpenAlex uniquement si le nom de
  l'entité auteur OpenAlex est compatible (`names_compatible`) avec
  le `raw_author_name` de l'authorship. Élimine les ORCID hérités d'un
  mismatch côté OpenAlex.
- **classification** : (a) — opère sur des champs déjà présents.
- **destination domain/** : `domain/sources/openalex_signals.py` →
  `keep_orcid_if_name_matches(raw_full_name, oa_full_name, oa_orcid) -> str | None`.

### règle allow_create pour rôles thèse
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:68-70`
- **description** : Invariant « les rôles non-auteur des thèses
  (directeurs, rapporteurs, jury) ne déclenchent jamais la création
  d'une nouvelle personne ». `allow_create = not (source == 'theses' and 'author' not in roles)`.
- **classification** : (a).
- **destination domain/** : `domain/persons/sourcing.py` →
  `allow_person_creation_from_authorship(source: str, roles: list[str]) -> bool`.

### décision de match par cross-source
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:189-198`
- **description** : Pour une authorship sans `person_id`, parcourt les
  candidats déjà rattachés à la même publication+position venus
  d'autres sources, choisit la `person_id` unique dont le nom est
  compatible. None si conflit (>1 person_id distincts).
- **classification** : (b) — prefetch `linked_index[(pub_id, position)]`.
- **destination domain/** : `domain/persons/matching.py` →
  `decide_cross_source_match(authorship_source, last_norm, first_norm, candidates) -> int | None`.

### décision de match par identifiant unique (IdRef, ORCID)
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:232-247` (idref) + `:272-287` (orcid)
- **description** : Si l'authorship porte un IdRef/ORCID présent dans
  la map identifier → person_id (statut non rejeté), rattacher.
  **Dupliqué structurellement** entre les deux types.
- **classification** : (b) — prefetch `idref_map`/`orcid_map`.
- **destination domain/** : `domain/persons/matching.py` →
  `decide_match_by_identifier(value, identifier_map) -> int | None`
  (générique, mutualise les deux).

### cascade de lookup par name_form
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:317-327`
- **description** : Construit l'ordre des formes de nom à essayer
  (`"prenom nom"`, `"nom prenom"`, `nom seul`) et renvoie la première
  trouvée dans `name_form_map`. Choix d'ordre = règle métier
  (prénom-nom prime).
- **classification** : (a).
- **destination domain/** : `domain/persons/matching.py` →
  `lookup_name_forms(last_norm, first_norm, name_form_map) -> list[int] | None`.

### arbitrage name_forms
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:328-358`
- **description** : Étape 3 : 1 person_id → match, plusieurs →
  ambigu, aucune forme connue + `allow_create` → créer, sinon ambigu.
  **Règle centrale du matching par nom**.
- **classification** : (b).
- **destination domain/** : `domain/persons/matching.py` →
  `decide_name_form_outcome(person_ids, allow_create) -> NameFormDecision`
  (`action ∈ {"match", "ambiguous", "create"}`).

### contrat de la cascade globale
- **localisation** : `application/pipeline/persons/create_persons_from_source_authorships.py:1-33` (docstring) + `:389-420` (orchestrateur)
- **description** : Hiérarchie de fiabilité (compte HAL > cross-source
  > IdRef > ORCID > nom), aujourd'hui dispersée. **Correspond à
  `decide_person_match` du chantier**.
- **classification** : (b) — prefetch des 5 résultats des étapes.
- **destination domain/** : `domain/persons/matching.py` →
  `decide_person_match(*, hal_account_match, cross_source_match, idref_match, orcid_match, name_form_outcome) -> PersonMatchDecision`.

---

## `application/pipeline/persons/populate_person_name_forms.py`

### règle de préservation des formes non bibliographiques
- **localisation** : `application/pipeline/persons/populate_person_name_forms.py:99-106`
- **description** : Une forme obsolète n'est supprimée que si toutes
  ses sources actuelles sont biblio (`hal`, `openalex`, `wos`, …) ;
  les formes portées par `persons` ou `manual` sont préservées (saisie
  RH ou intervention humaine = vérité).
- **classification** : (a).
- **destination domain/** : `domain/persons/sourcing.py` →
  `can_delete_obsolete_name_form(sources: set[str]) -> bool`.

### enrichissement d'une forme par fusion de sources
- **localisation** : `application/pipeline/persons/populate_person_name_forms.py:61-75`
- **description** : Quand une forme apparaît à la fois en source
  `persons` et en source biblio, fusionne `person_ids` (union triée)
  et `sources` (union triée). Invariant « une forme = ensemble de
  person_ids candidats × ensemble de sources qui l'ont vue ».
- **classification** : (a).
- **destination domain/** : `domain/persons/sourcing.py` →
  `merge_name_form_provenance(existing, additional_pid, additional_source) -> NameFormEntry`.

### diff existant vs recalculé
- **localisation** : `application/pipeline/persons/populate_person_name_forms.py:87-97`
- **description** : Compare l'ensemble actuel à celui recalculé pour
  décider INSERT / UPDATE silencieux / no-op.
- **classification** : (b) — décision pure si on prefetch la map.
  Marginal.
- **destination domain/** : `domain/persons/sourcing.py` →
  `decide_name_form_diff(new, old) -> Literal["insert","update","noop"]`
  (à ne rapatrier que si on veut les tests dédiés).

### compute_person_name_forms
- **localisation** : `application/pipeline/persons/populate_person_name_forms.py:36`
  (consomme `application.persons.compute_person_name_forms`)
- **description** : Génération des deux variantes "prénom nom" /
  "nom prénom". Pure dépendant uniquement de `last_name`/`first_name`.
- **classification** : (a) — pure mais hébergée en `application/`.
- **destination domain/** : `domain/persons/sourcing.py` →
  `compute_person_name_forms(last_name, first_name) -> list[str]` (à
  rapatrier).

---

## `application/pipeline/publications/create_publications.py`

### prérequis de création d'une publication
- **localisation** : `application/pipeline/publications/create_publications.py:42-44`
- **description** : Une publication ne peut être créée que si elle a
  au minimum titre + année. Invariant métier.
- **classification** : (a).
- **destination domain/** : `domain/publications/dedup.py` →
  `has_minimal_publication_metadata(title, pub_year) -> bool` (ou
  invariant documenté en haut de `decide_publication_match`).

### normalisation pre-lookup
- **localisation** : `application/pipeline/publications/create_publications.py:48,57,68,69`
- **description** : Avant lookup, canonicalise `doc_type` (via
  `map_doc_type`), `nnt` (via `normalize_nnt`), `title_normalized`
  (via `normalize_text`).
- **classification** : (a) — déjà domain.
- **destination domain/** : n/a.

### cascade dedup DOI > NNT > titre+année+journal
- **localisation** : `application/pipeline/publications/create_publications.py:62-76`
  (délégué à `application.publications.find_or_create`)
- **description** : Recherche en cascade DOI > NNT > (titre normalisé +
  année + journal). **Règle centrale de déduplication**.
- **classification** : (b) — décomposable (déjà couvert par
  `find_or_create` ci-dessus).
- **destination domain/** : `domain/publications/dedup.py` →
  `decide_publication_match` (même fonction).

---

## `application/pipeline/publications/merge_pubs_by_hal_id.py`

### identification des doublons par hal_id
- **localisation** : `application/pipeline/publications/merge_pubs_by_hal_id.py:25-72`
- **description** : Croise `source_publications` HAL et celles
  d'autres sources portant un `hal_id` dans `external_ids` ; classe
  chaque correspondance en `link_only` (HAL non rattaché) vs
  `merge_needed` (deux `publication_id` distincts à fusionner).
- **classification** : (b) — décision pure si on lui passe les deux
  listes de rows.
- **destination domain/** : `domain/publications/dedup.py` →
  `classify_hal_id_duplicates(hal_rows, other_source_rows) -> tuple[list[LinkAction], list[MergeAction]]`.

### règle de préservation de la publication HAL
- **localisation** : `application/pipeline/publications/merge_pubs_by_hal_id.py:99-110, :138-143`
- **description** : Quand deux publications partagent un hal_id, on
  conserve celle portée par HAL et on fusionne l'autre dedans. HAL
  prime comme entité de référence.
- **classification** : (a).
- **destination domain/** : `domain/publications/merge.py` →
  `pick_canonical_publication_by_source_priority(target_source_priority, candidates) -> int`.

### résolveur de chaînes de fusion
- **localisation** : `application/pipeline/publications/merge_pubs_by_hal_id.py:115-122`
- **description** : Pendant un batch, suit les redirections
  `pub_id → pub_id_cible` accumulées pour ne pas fusionner vers une
  publication elle-même déjà fusionnée (avec garde anti-cycle). La
  cible finale doit toujours être l'entité encore vivante.
- **classification** : (a).
- **destination domain/** : `domain/publications/merge.py` →
  `resolve_merge_redirect(pub_id, redirects) -> int`.

### déduplication des paires à fusionner
- **localisation** : `application/pipeline/publications/merge_pubs_by_hal_id.py:42-43, 60-69`
- **description** : Pour un même `hal_doc_id`, ignorer les link_only
  redondants ; pour une même paire `(src_pub, hal_pub)`, ne demander
  qu'une seule fusion.
- **classification** : (a).
- **destination domain/** : intégré dans `classify_hal_id_duplicates`.

---

## `application/pipeline/publications/merge_pubs_by_nnt.py`

### détection des doublons par NNT
- **localisation** : `application/pipeline/publications/merge_pubs_by_nnt.py:29`
- **description** : Trouve les NNT pour lesquels plusieurs `publication_id`
  distincts existent. Invariant cible : un NNT identifie une thèse
  unique.
- **classification** : (c) — détection en SQL.
- **destination domain/** : n/a (invariant déjà porté par le VO `NNT`).

### choix de la publication cible de fusion
- **localisation** : `application/pipeline/publications/merge_pubs_by_nnt.py:44-48`
  (délégué à `queries.rank_publications_by_merge_priority`)
- **description** : Parmi N publications partageant un NNT, choisit
  la cible par tri par priorité (sources, ancienneté, complétude).
  Tri aujourd'hui en SQL.
- **classification** : (b) — prefetch des publis avec leurs sources,
  dates, complétude.
- **destination domain/** : `domain/publications/merge.py` →
  `rank_publications_by_merge_priority(pubs: list[PubMergeCandidate]) -> list[int]`.

### invariant idempotence chaîne de fusions
- **localisation** : `application/pipeline/publications/merge_pubs_by_nnt.py:60-67`
- **description** : Chaque fusion encadrée par savepoint, l'erreur d'une
  fusion ne fait pas tomber le batch. Pas de logique de redirection
  ici (contrairement à hal_id) — opportunité de durcir.
- **classification** : (c).
- **destination domain/** : n/a.

---

## `application/pipeline/authorships/build_authorships.py`

### ordre canonique des sources pour propagation
- **localisation** : `application/pipeline/authorships/build_authorships.py:20-26`
- **description** : Liste ordonnée
  `[HAL, OpenAlex, WoS, ScanR, theses.fr]` qui définit l'ordre dans
  lequel `in_perimeter` et `structure_ids` sont propagés vers la table
  `authorships` (table de vérité).
- **classification** : (a).
- **destination domain/** : `domain/sources.py` (déjà existant) →
  exposer `BUILD_AUTHORSHIP_SOURCE_ORDER` (ou réutiliser
  `SOURCES_BY_PRIORITY` si déjà en place).

### règle du full run pour reset
- **localisation** : `application/pipeline/authorships/build_authorships.py:31-32, 51-56`
- **description** : Le reset du périmètre+structures n'a lieu que si
  toutes les sources sont actives. En run partiel, on n'écrase pas
  ce que les autres sources ont propagé.
- **classification** : (a).
- **destination domain/** : `domain/sources.py` ou
  `domain/persons/sourcing.py` →
  `should_reset_before_propagation(active_sources, all_sources) -> bool`.

### invariant union des structures par source
- **localisation** : `application/pipeline/authorships/build_authorships.py:58-63`
- **description** : `authorships.in_perimeter` est un OR logique sur
  les sources et `structure_ids` est l'union des `structure_ids`
  portés par les `source_authorships` rattachées. Invariant de la
  table de vérité.
- **classification** : (b) — règle pure mais aujourd'hui exécutée en
  SQL côté query (perf). À garder en SQL pour la prod, formaliser
  l'invariant en domain comme contrat testé.
- **destination domain/** : `domain/persons/sourcing.py` →
  `aggregate_authorship_perimeter(source_rows) -> tuple[bool, list[int]]`
  (utile pour les tests).

### étapes de construction de la table authorships
- **localisation** : `application/pipeline/authorships/build_authorships.py:1-11, :37-49`
- **description** : Séquence ordonnée des 4 étapes (insertion, FK,
  position/corresponding, perimeter/structures). Chaque étape suppose
  la précédente faite.
- **classification** : (c).
- **destination domain/** : n/a.

---

## Synthèse globale

### Comptage par classification

| Classification | Périmètre 1<br>(normalize/* + persons.py + publications.py) | Périmètre 2<br>(pipeline/persons + pipeline/publications + pipeline/authorships) | **Total** |
|---|---:|---:|---:|
| **(a) déjà pure** | 25 | 14 | **39** |
| **(b) décomposable** | 12 | 10 | **22** |
| **(c) intrinsèque transaction** | 2 | 3 | **5** |
| **Total** | 39 | 27 | **66** |

### Patterns dupliqués majeurs

1. **Découpage naïf last_name/first_name** sur full_name — verbatim
   dans `normalize_hal.py:383-389` et `normalize_scanr.py:270-276`.
   À unifier dans `domain/names.split_full_name_naive`.

3. **Invariant « source_persons créé seulement si identifiant fort »**
   — répété dans HAL (`hal_person_id`), ScanR (`idref`), theses
   (`PPN`). À unifier dans
   `domain/persons/sourcing.should_create_source_person`.

5. **Règle `doc_type theses` (`thesis` vs `ongoing_thesis`)** —
   dupliquée dans `normalize_theses.py:88` et `:247`. À unifier dans
   `domain/doc_types.theses_doc_type` (mentionné dans le doc chantier).

6. **Cascade de matching publication multi-source** (DOI/NNT/title/source-id)
   — implémentée 5 fois, une par source : HAL, OpenAlex, WoS, ScanR,
   theses, Crossref. Toutes variantes de `decide_publication_match`.
   À unifier dans `domain/publications/dedup.py`.

7. **Match par identifiant unique → person_id** — trois clones
   structurellement identiques (cross-source, IdRef, ORCID) qui ne
   diffèrent que par la map de prefetch. À mutualiser en
   `decide_match_by_identifier(value, identifier_map)` dans
   `domain/persons/matching.py`.

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

À enrichir dans `domain/names.py` :

- `split_full_name_naive(full_name) -> tuple[str | None, str]`

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
def extract_thesis_year(date_soutenance: str | None, date_inscription: str | None) -> int | None: ...
def thesis_authors_compatible(candidate, claimed) -> bool: ...
def aggregate_thesis_persons(these: dict) -> list[ThesisAuthorship]: ...

# domain/persons/identifiers.py
def build_authorship_identifiers(source: str, **fields) -> dict | None: ...
def iter_identifier_writes(authorships) -> Iterable[IdentifierWrite]: ...
def pick_idhal_from_tei_idnos(idnos: list) -> dict[str, str]: ...
IDENTIFIER_FIELDS_BY_SOURCE: dict[str, IdentifierConfig]

# domain/persons/sourcing.py
def should_create_source_person(source: str, *, strong_id) -> bool: ...
def allow_person_creation_from_authorship(source: str, roles: list[str]) -> bool: ...
def compute_person_name_forms(last_name: str, first_name: str | None) -> list[str]: ...
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
def extract_nnt_from_scanr_id(scanr_id: str) -> str | None: ...

# domain/sources/crossref_signals.py
def extract_crossref_pub_year(msg: dict, *, max_year: int) -> int | None: ...
def parse_crossref_issns(msg: dict) -> tuple[str | None, str | None]: ...
def strip_jats_tags(s: str) -> str: ...
def extract_crossref_meta(msg: dict) -> dict | None: ...

# domain/sources/wos_signals.py
def is_wos_author_exploitable(author: dict) -> bool: ...

# domain/sources/hal_signals.py
def pick_hal_structure_field(doc: dict) -> Literal["primary", "flat"]: ...

# domain/names.py (existant, à enrichir)
def split_full_name_naive(full_name: str) -> tuple[str | None, str]: ...

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
- `application/persons.py:_SOURCE_CONFIG` (l. 313) n'est utilisé
  nulle part dans le fichier scanné — vraisemblablement consommé
  ailleurs. À confirmer hors périmètre.
- L'invariant `check_can_merge_persons` dans `domain/person.py` est le
  pattern de référence à reproduire pour les autres règles
  décisionnelles (déjà cité dans le doc chantier aux côtés de
  `resolve_doi_conflict`).
