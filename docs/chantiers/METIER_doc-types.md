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

## Reste à faire

Pris dans l'ordre :

- [x] Book reviews par titre — règles ISBN + année-pages posées (`27e7b1f7`)
- [x] Préprints article + journal_id inconnu — audit fait, règle `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` posée (`c8be3409`)
- [ ] Préprints OA gold — flag suspect ← **cible courante**
- [ ] Types WoS composites — audit
- [ ] Review = poubelle — audit (à coupler avec book_review une fois traité)
- [ ] Figshare collections — audit
- [ ] Posters / conférence avec même DOI — hors-scope correction, à traiter en dédup
- [ ] Question des raw_type openalex: comparer avec le type affiché

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

### Types WoS composites — audit

Aujourd'hui `map_doc_type` prend le **premier** type non-other quand WoS renvoie `"Article; Proceedings Paper"`. C'est arbitraire — sur des paires `Article; Book Chapter` le bon choix peut être le second. Pas un vrai mapping.

Étape suivante : audit. Pour chaque paire observée (ex. `Article; Proceedings Paper`, `Article; Book Chapter`, `Review; Book Chapter`), compter les occurrences et sonder quelques cas pour décider de la règle (et si la règle doit dépendre du journal). Puis remplacer le `first non-other` par un arbitrage explicite par paire.

### Review = poubelle — audit

Le doc_type `review` amalgame plusieurs choses :

- WoS `review` = review article (revue de la littérature) ⇒ `review`
- HAL `art_artrev` = mappé vers `review` aujourd'hui
- OpenAlex `review` = un peu de tout
- Recensions d'ouvrages (book reviews) ⇒ devraient aller en `book_review` mais sont parfois en `review`

Étape suivante : audit. Sonder les publications canoniques classées `review` et leur source, voir ce que ça recouvre vraiment. Ajuster les mappings et écrire une règle de désambiguïsation (titre, journal) si nécessaire. À mener avec book_review (mêmes cas observés probablement).

### Figshare collections — audit

DOI `10.6084/m9.figshare.c.*` (bundles de plusieurs items figshare). Non couvert par la règle titre supplément. Cas connu mais ampleur inconnue ; ne choque pas a priori d'être rattaché à un article.

Étape suivante : audit. Combien, classés en quoi aujourd'hui, à quoi sont-ils rattachables.

### Préprints OA gold — flag suspect

Une publication marquée `preprint` par OpenAlex mais avec `oa_status=gold` est probablement un cas mal classé (un vrai preprint n'est pas en accès gold). À auditer puis décider d'une règle ou d'un flag de doute.

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
