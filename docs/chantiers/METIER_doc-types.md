# Chantier — Types de documents : enum, mappings, règles suspects

Issu de [`regles-metier-domain.md`](regles-metier-domain.md) (Phase 2 historique) + items TODO_LAURA « Types de documents : fixer l'enum et le mapping, algo de résolution de conflits ».

## Contexte

Trigger initial : sondage 2026-05-05 sur les ~300 publis avec DOI figshare. **229 sont des « Additional file X of … »** (suppléments PDF figures/tableaux), classées « article » par OpenAlex donc remontées comme telles dans la BDD UCA. La règle qui aurait dû les écarter n'existait nulle part. Elle a depuis été écrite (`TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`, cf. ci-dessous).

Le chantier sert maintenant à finir de cartographier les types problématiques et à écrire les règles manquantes ou les audits préalables.

## Fait

Règles de correction en place dans [`domain/publications/correction.py`](../../domain/publications/correction.py) :

- `THESES_FR_URL_TO_THESIS` — URL theses.fr ⇒ `thesis`
- `DUMAS_URL_TO_MEMOIR` — URL dumas + `dissertation` ⇒ `memoir`
- `JOURNAL_TYPE_MEDIA_TO_MEDIA` — journal typé media ⇒ `media`
- `JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER` — journal d'actes + `{article, book_chapter}` ⇒ `conference_paper`
- `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` — serveur de preprints + `{article, other}` ⇒ `preprint`. Sans effet aujourd'hui (aucun journal typé `preprint_server` en base UCA, à faire côté admin) ; en place pour quand le typage sera posé.
- `TITLE_MEDIA_PREFIX_TO_MEDIA` — titre `interview/reportage/podcast` ⇒ `media`
- `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET` — titre supplément (additional file, supplementary *, data from) ⇒ `dataset` (couvre figshare items, Zenodo, DataCite via le titre, plus large que des helpers DOI-préfixe envisagés au départ)
- `TITLE_ERRATUM_PREFIX_TO_ERRATUM` — titre `erratum/errata/corrigendum` ⇒ `erratum`
- `TITLE_RETRACTION_PREFIX_TO_RETRACTION` — titre `retraction notice/note` ⇒ `retraction`
- `TITLE_ISBN_TO_BOOK_REVIEW` — ISBN ou ISBN-13 nu dans le titre + doc_type ∈ {article, review, other} ⇒ `book_review`
- `TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW` — titre terminé par « (19|20)YY, N p[.|ages] » + mêmes whitelist ⇒ `book_review`

Enum `doc_type` et mappings ([`domain/publications/doc_types.py`](../../domain/publications/doc_types.py)) :

- Membres ajoutés : `erratum`, `retraction`, `book_review`, `data_paper`, `proceedings`, `media`, `poster`, `letter`, `peer_review`, `memoir`, `hdr`, `ongoing_thesis` — labels FR singulier/pluriel posés.
- Mapping HAL : sous-types composites pris en compte (`art_artrev`→review, `art_bookreview`→book_review, `art_datapaper`→data_paper, `undefined_preprint`→preprint, `creport_resreport`→report, …).
- Mapping WoS : `correction`→erratum, `news item`→media, `book review`→book_review, `data paper`→data_paper, `meeting abstract`→conference_paper.
- Mapping CrossRef ajouté.

Playbook [`ajouter-une-regle-de-correction.md`](../playbooks/ajouter-une-regle-de-correction.md) posé. Documente la procédure complète (caractérisation, audit, implémentation, tests, hooks admin si éditable, rattrapage du stock).

**Hooks de requalification** (re-jouer la cascade de correction quand le contexte journal d'une publication change) : changement de `journal_type` via `update_journal` (preview `type-change-impact` + confirmation) **et** fusion de journaux — fusionner dans un journal d'un autre type requalifie les `doc_type` des publications absorbées contre le type de la cible (revue → média ⇒ `media`). Backend dans `merge_journals` (`1a9bce2c`, couvre le merge direct et la cascade de `merge_publishers`), preview + confirmation frontend symétrique du changement de type (`15bbfc4a`).

## Reste à faire

Pris dans l'ordre :

- [x] Book reviews par titre — règles ISBN + année-pages posées (`27e7b1f7`)
- [x] Préprints article + journal_id inconnu — audit fait, règle `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` posée (`c8be3409`)
- [x] Préprints OA gold — audit fait : `gold` est une mauvaise lentille ; signal réel = `preprint + journal_id` (215 publis), cause = arbitrage canonique. Résolution non tranchée (cf. section)
- [x] Types WoS composites — audit fait (sur raw store) : 388 composites ; réduction `doctype_list[0]` au normalize ; `Data Paper` perdu, `Book Chapter`/`Proceedings Paper` à trancher (cf. section)
- [x] Review = poubelle — audit fait : **pas une poubelle**, mappings sains ; seule action = libellé FR « Article de synthèse »
- [x] Figshare collections — audit fait + règle `DOI_FIGSHARE_COLLECTION_TO_DATASET` ; dédup des sous-items → relations
- [ ] Posters / conférence avec même DOI — hors-scope correction, à traiter en dédup

### Préprints article + journal_id inconnu

Audit 2026-05-28 sur les 744 publications canoniques `doc_type=article` + `journal_id IS NULL` (4.1% des articles). Le périmètre se décompose en au moins trois sous-cas qui ne sont **pas** tous des préprints :

- **162 WoS sans DOI, titres en majuscules** (ex. « MYCENAEAN PAINTING », « ARTWORKS IN CONTEXT The Historical Framework ») — `raw doc_type = 'article'` brut WoS (pas un composite). Plusieurs SPs WoS par publi (signe d'un import multiple). **Pas des préprints** — souvent les versions EN traduites de publis déjà présentes en base avec leur titre FR d'origine (autre source), ce qui rend la sim_titre cross-langue impossible. Laissé de côté pour ce chantier ; correction ponctuelle si remontée.
- **67 publis EGU/Copernicus** (DOI `10.5194/egusphere-*`) : mélange de deux familles distinguées par sous-pattern du DOI — `egusphere-egu<YY>-*` = abstracts de la conférence EGU General Assembly (→ `conference_paper`) vs `egusphere-<YYYY>-*` = preprints du serveur EGUsphere (→ `preprint`). Les SPs OA disent 212 `preprint` / 116 `article` / 61 `peer-review` mais l'arbitrage canonique les surclasse en `article` (cf. point ci-dessous sur `_first_doc_type`).
- **335 avec `container_title` renseigné**, profilées en passe 2 (sondage par top container) :
  - **~51 vrais preprint servers** (SSRN 30 + bioRxiv 14 + arXiv 5 + ChemRxiv 2) — DOI préfixes 10.2139/ssrn.*, 10.64898/*, 10.48550/arxiv.*, 10.26434/chemrxiv*. Éligibles à `journal_type=preprint_server` côté admin ; la règle se déclenchera au refresh.
  - **~173 repositories institutionnels** (HAL 73, Zenodo 66, ZORA 21, SPIRE 13) — hétérogènes : preprints, articles peer-reviewed déposés en Green OA (cas vu sur ZORA : papier ATLAS/LHCb avec son vrai journal ailleurs), datasets, posters. **Pas de règle `JOURNAL_TYPE_REPOSITORY_TO_*`** envisageable : pas de mapping déterministe. Bon traitement = meilleur rattachement journal_id vers le journal de publication d'origine, relève du matching journal (hors-scope doc-types).
  - **~78 datasets Figshare/Open MIND** (67 + 11) — DOI 10.6084/m9.figshare.* tous en « Additional file 1 of … ». `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET` les couvre déjà ; stock à rattraper via [`oneshot/refresh_publications_with_supplementary_content_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_supplementary_content_title.py).
  - **~11 vrais journaux mal-rattachés** : AUGC 6 (Academic Journal of Civil Engineering, DOI 10.26168/ajce.*) et LIPIcs/Dagstuhl 5 (10.4230/lipics.*). Bug de matching journal, renvoyé vers [METIER_publishers-journals](METIER_publishers-journals.md).
  - **~5 PubMed** — artefact normalizer OpenAlex (pose « PubMed » en host_venue quand l'info journal manque). À creuser séparément.

**Règle métier** : `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` codée (cf. section Fait), sans effet tant qu'aucun journal n'est typé `preprint_server` en base.

**Bloquant rattachement journal_id** : la colonne `journals.doi_prefix` existe (singulière) mais n'est remplie pour aucun des 15 659 journaux. Pour Copernicus le préfixe DOI (`10.5194`) ne suffit pas — il faut un sous-pattern (`egusphere-egu*`, `acp-*`, …) pour distinguer plusieurs journaux d'un même préfixe. La mécanique de remplissage de `doi_prefix` et la question du sous-pattern relèvent d'un chantier dédié, hors-scope ici.

**À creuser séparément** : l'arbitrage canonique du `doc_type` (`application/publications._first_doc_type`) qui surclasse `preprint` (brut OA) en `article` même quand 212 SPs sur 389 disent `preprint`. Comportement non-trivial à expliquer ou corriger.

### Types WoS composites — audit ✓

Correction d'une hypothèse de la fiche : ce n'est **pas** `map_doc_type` qui réduit le composite (son découpage « ; » est du code mort pour WoS). La réduction se fait bien plus tôt, au normalize : [`application/pipeline/normalize/normalize_wos.py`](../../application/pipeline/normalize/normalize_wos.py) prend `doctype_list[0]` (premier élément) et jette le reste. `source_publications.doc_type` ne contient donc jamais de composite — d'où 0 composite en base alors que le brut en a.

Audit 2026-06-04 sur le **raw store** (`data/raw_store/wos/`, 15 276 fichiers ; champ brut `static_data.summary.doctypes.doctype`, liste si `count > 1`) : **388 composites** (2,5 %).

| Paire WoS | n | Verdict |
|---|---|---|
| `*; Early Access` (Article 143, Review 17, Editorial 11, Letter 5, Correction 1) | 177 | « Early Access » = stade de publication, pas un type. La réduction « premier » est **correcte** (le vrai type est en tête). À garder. |
| `Article; Book Chapter` | 131 | À trancher (article en série d'ouvrage vs `book_chapter`). Sonder. |
| `Article; Proceedings Paper` | 37 | Probable `conference_paper` (le second porte l'info). À trancher. |
| `Article; Data Paper` | 25 | **Mistypage** : `data_paper` (sous-type informatif) est perdu → devrait gagner. |
| `Editorial Material; Book Chapter` | 14 | À trancher. |
| `Review; Book Chapter` | 3 | À trancher. |
| `Correction; Early Access` | 1 | → `erratum`. |
| `Article; Publication with Expression of Concern` | 1 | Edge. |

**Conclusion.** Le « premier élément » est bon pour les paires `*; Early Access` (3/4 des composites) mais mistype les paires où le second terme est le type réel/informatif (`Data Paper` sûr ; `Proceedings Paper`, `Book Chapter` à trancher). Fix = remplacer `doctype_list[0]` dans `normalize_wos` par une réduction qui (a) ignore les tokens de stade (`Early Access`), (b) préfère le sous-type le plus spécifique. Décisions par paire `Book Chapter` / `Proceedings Paper` non tranchées.

### Review = poubelle — audit ✓

Audit (base de prod) : `review` = 1382 publis. Signal review par source : WoS `review` 1006, OpenAlex `review` 980, HAL `art_artrev` 299. **84 %** ont un signal WoS ou HAL-`art_artrev` (review articles certains) ; les **16 % « OpenAlex seul »** (227) sont, à l'échantillon, ~90 %+ de vrais review articles (systematic/narrative reviews, position papers, recommandations) — pas des recensions, pas du media.

**Conclusion : `review` n'est pas une poubelle.** Type cohérent (review article / revue de littérature), alimenté légitimement par WoS, HAL `art_artrev` **et** OpenAlex (l'hypothèse « OA review = un peu de tout » ne tient pas). Pas de fuite de book reviews : HAL `art_bookreview` et WoS `book review` → `book_review`, et les règles titre (ISBN, année-pages) attrapent le reste ; l'échantillon OA-seul n'en montre aucune. **Aucun changement de mapping ni règle de désambiguïsation.** Seul bruit résiduel : une poignée de mistypes OA (ex. « Publisher Correction: … » = erratum classé review) — marginal, relève d'un trou de détection erratum côté OA.

**Seule action** : libellé FR `review` « Review » → « Article de synthèse » (terme standard, cf. HAL). Au passage `letter` « Letter » → « Lettre à l'éditeur » (audit : 266 publis, OpenAlex+WoS `letter`, majoritairement lettres à l'éditeur / correspondance).

### Figshare collections — audit ✓

DOI `10.6084/m9.figshare.c.*` (bundles de suppléments ; le `.c.` distingue une collection d'un item `m9.figshare.<id>`). Une collection = bundle des suppléments d'un papier (l'article réel est ailleurs, sous son DOI de revue) ; figshare la nomme d'après le papier, donc titre « normal » → inattrapable par la règle titre supplément.

Audit (base prod) : **73 collections**, classées **71 `other`** + 1 article + 1 dataset (OpenAlex `other`). Pas de mistype `article` comme pour les items.

**Règle posée** : `DOI_FIGSHARE_COLLECTION_TO_DATASET` — `doi_contains 'm9.figshare.c.'` + doc_type ∈ {article, other} ⇒ `dataset` (nouveau prédicat réutilisable `doi_contains`). Fallback hardcodé ; RA DataCite généraliserait aux figshare institutionnels plus tard.

**Renvoyé à [METIER_relations-publications](METIER_relations-publications.md)** : la **dédup des sous-items**. 273/281 items suivent « Additional file N of <T> », **212 matchent exactement** le titre d'une collection (70/73 collections ont ≥1 item) — le lien item→collection est donc fiable par titre. Mais supprimer les sous-items ne règle qu'à moitié (les collections restent des doublons du vrai article) ; le traitement complet (collection↔item **et** supplément↔article) se modélise dans le chantier relations.

### Préprints OA gold — audit ✓

`gold` (publié dans une revue intégralement OA) est en principe incompatible avec `preprint` — un préprint en repository est `green`, pas `gold`. Audit 2026-06-04 (base prod) : 125 publis `doc_type=preprint` + `oa_status=gold`. Décomposition :

- **~118 sans `journal_id`** : vrais préprints sur serveurs ouverts (ESSOAr `10.1002/essoar`, PsyArXiv/SocArXiv/EarthArXiv `osf.io`, EGUsphere `egusphere-YYYY`, Authorea, Research Square) et *Discussions* Copernicus (acpd/nhessd/amtd). `doc_type=preprint` est correct ; c'est `oa_status=gold` qui est sur-étiqueté par OpenAlex (il associe la revue-mère gold au DOI de discussion). Le champ erroné est `oa_status`, rapporté par la source → non corrigé ici. **Pas une erreur de doc_type.**
- **~24 abstracts de conférence** (EGU `egusphere-egu*`, EPSC `epsc-dps*`, workshops) → devraient être `conference_paper`. Sous-pattern DOI Copernicus déjà identifié et **parké** (bloqué sur `journals.doi_prefix` + sous-pattern, hors-scope).
- **7 avec un `journal_id` réel** = les vraies contradictions (Physics Letters B, Scientific Reports ×2, JHEP, F1000, eLife ×2).

**`gold` n'est qu'une lentille étroite.** Le signal propre est `doc_type=preprint` **+ `journal_id IS NOT NULL`** : **215 publis** (toutes `oa_status`). Un préprint rattaché à une vraie revue est la contradiction.

**Cause racine — l'arbitrage canonique.** `arbitrate_doc_type_with_article_subtype` (`domain/publications/aggregation.py`) retourne le `doc_type` de la première source par `SOURCE_PRIORITY`, avec pour seule finesse le raffinement article→sous-type. Il ne tranche jamais **preprint vs publié** : quand une source indexe à la fois le preprint et la version publiée (OpenAlex, ScanR), si le SP `preprint` est rencontré en premier, `preprint` gagne — même contre 4 sources disant Article + revue + gold (cas Scientific Reports). `preprint` n'étant pas un sous-type d'article, l'exception ne joue pas.

**Réserves.**
- eLife / F1000Research sont des revues **gold OA** à workflow « publier puis réviser » (*reviewed preprints*) : leur DOI sort légitimement preprint + gold. Les basculer en `article` est défendable mais reste un choix.
- Certains `journal_id` sont eux-mêmes faux (vu : `egusphere-egu24-197` rattaché à « BioRxiv ») — basculer aveuglément en `article` propagerait une revue erronée. Bug de matching journal en amont.

**Piste de résolution (non tranchée).** Pas une règle titre/DOI mais un fix d'arbitrage : *une publication avec une revue résolue ne doit jamais être canoniquement `preprint`* (`preprint` perd face à un signal Article/Review adossé à un `journal_id`). Couvre les 215, laisse les préprints-serveurs sans revue intacts, cohérence garantie au rebuild. À décider : fix arbitrage vs règle de correction vs flag suspect ; et traitement eLife/F1000.

### Posters / conférence avec même DOI

Détection de doublons en dédup, pas une règle de correction. À traiter quand on touche la dédup, ou en marge si un cas saute pendant un audit.

## Décisions actées

1. **Détection figshare/Zenodo : pour les items, gérée par le titre** (`TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`). Plus large que la détection par préfixe DOI envisagée au départ : couvre aussi Dryad/IFREMER, et reste valable même si un fichier supplément est posé sur un domaine autre. La détection RA via [doi-ra-datacite](METIER_doi-ra-datacite.md) reste utile pour d'autres règles (ex. figshare collections, qui ont des titres "normaux" et ne sont pas attrapées par le pattern titre).
2. **Reclassement one-shot des cas existants** en fin de chantier. SQL aligné sur la nouvelle règle, suivi d'une passe de vérification au prochain run pipeline pour s'assurer que la cascade en `domain/` produirait le même résultat. Modèle : [`oneshot/refresh_publications_with_supplementary_content_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_supplementary_content_title.py).
3. **Pas de règle `JOURNAL_TYPE_REPOSITORY_TO_*`**. Les repositoires institutionnels (HAL, Zenodo, ZORA, SPIRE…) hébergent indifféremment des preprints, des articles peer-reviewed en Green OA, des datasets et des posters — aucun mapping `doc_type` déterministe possible depuis le seul `journal_type=repository`. Le bon traitement des publis hébergées sur repository est un meilleur rattachement journal_id vers le journal de publication d'origine, pas un retypage.

## Hors scope

- L'ingestion DataCite proprement dite : couverte par [METIER_doi-ra-datacite](METIER_doi-ra-datacite.md). Ce chantier-ci se contente d'utiliser les helpers/données qui en sortent.
- Modifications du schéma SQL au-delà de l'enum `doc_type` : décisions au cas par cas.
- **Suppléments figshare orphelins** (145 cas au 2026-05-05 dont le parent n'est pas en BDD) : déplacé dans [METIER_relations-publications](METIER_relations-publications.md). Rejoint un chantier de modélisation des relations entre publications.

## Risques

- **Performance** : les comparaisons sur titre passent par `normalize_text` + `startswith` / regex compilées module-level. Patterns compilés à l'import, pas à chaque appel.
- **Coordination avec [doi-ra-datacite](METIER_doi-ra-datacite.md)** : la détection RA peut bénéficier de `doi_prefixes` plutôt que d'un hardcode. À séquencer après doi-ra-datacite phase 1, ou en parallèle avec un fallback hardcodé.

## Liens

- [METIER_metadata-correction](METIER_metadata-correction.md) — patron architectural des règles de correction, point unique d'implémentation (`effective_metadata`).
- [`ajouter-une-regle-de-correction.md`](../playbooks/ajouter-une-regle-de-correction.md) — playbook procédural.
- [METIER_doi-ra-datacite](METIER_doi-ra-datacite.md) — détection RA via préfixe, prérequis pour les règles figshare collections et préprints article OA.
- [METIER_relations-publications](METIER_relations-publications.md) — absorbe les orphelins figshare et tout ce qui touche aux liens sémantiques entre publications.
- État actuel : [`domain/publications/correction.py`](../../domain/publications/correction.py), [`domain/publications/doc_types.py`](../../domain/publications/doc_types.py), [`application/publications.py`](../../application/publications.py) (`refresh_from_sources`).
