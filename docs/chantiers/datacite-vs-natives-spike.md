# Spike — DataCite vs APIs natives (Phase 3)

Note de synthèse du spike `interfaces/cli/oneshot/datacite_vs_natives_spike.py`. Payloads bruts dans `docs/chantiers/datacite-vs-natives-spike-data/`. Objectif : aider à trancher la Phase 3 du chantier `METIER_doi-ra-datacite` — DataCite seul, extracteurs natifs, ou mix.

## Méthode

Pour chaque repository phare :
- Tirage aléatoire (seed=42) de N DOIs UCA réels parmi les préfixes attribués au client DataCite correspondant.
- Pour chaque DOI : requête `api.datacite.org/dois/{doi}` + requête API native.
- Conservation des payloads bruts (pas de présélection de champs côté script — l'inventaire se fait sur les JSON).
- Option (a) retenue : on ne garde que les DOIs où l'API native répond 200. Orphelins (404 natif) exclus.

Paramètres : `--sample-size 12 --seed 42`.

## Zenodo (préfixe `10.5281`, client `cern.zenodo`)

- API native : `https://zenodo.org/api/records/{record_id}` où `record_id` = partie après `10.5281/zenodo.`
- **12/12 paires complètes** (DataCite + Zenodo). Pas de 404, pas de désappariement.

### Couverture par champ (lecture sur 1 sample détaillé + tendances)

| Champ biblio | DataCite | Zenodo natif | Verdict |
|---|---|---|---|
| `creators` (nom, ORCID, affiliation) | Structuré (nameType, givenName/familyName, nameIdentifiers avec scheme explicite) | Plus plat (name, affiliation string, orcid string) | Match exact en contenu, **DataCite plus normalisé** |
| `fundingReferences` / `grants` | funderName + funderIdentifier + awardNumber + awardTitle | Plus riche : program (HORIZON.4.1), acronym, URL CORDIS | **Zenodo plus riche métier**, DataCite suffit pour le matching funder |
| `rightsList` / `license` | SPDX identifier + URI + scheme | `id` seul (ex. `cc-by-4.0`) | **DataCite plus riche** |
| `relatedIdentifiers` | 1-4 entrées, inclut `IsVersionOf` auto-généré entre versions | 0-1 entrée, manque les `IsVersionOf` | **DataCite plus riche** (curieusement) |
| `subjects` / `keywords` | `subjects[]` structuré | `keywords[]` plat | Comparable |
| `titles`, `descriptions`, `publicationYear`, `publisher` | Tous présents | Tous présents | Équivalent |
| Compteurs (`viewCount`, `downloadCount`, `citationCount`) | Présents | Pas dans la racine, dans `stats` | DataCite plus pratique si on veut ces chiffres |
| `files` (URL téléchargement, checksum, taille) | Absent | Présent | Zenodo seul (pas un besoin biblio) |
| `geoLocations` | Présent quand renseigné | Absent | DataCite seul (pas un besoin biblio actuel) |

**Lecture** : sur les champs qui nous intéressent (auteurs+ORCID, affiliations, funder, license, doc_type, relations entre publications), **DataCite est au moins équivalent et souvent plus riche que Zenodo natif**. L'écart « Zenodo plus riche » (grants détaillés CORDIS, fichiers) ne concerne pas le périmètre biblio actuel.

## INRAE (préfixes `10.14758`, `10.15454`, `10.17180`, client `inist.inra`)

Hypothèse de départ : INRAE = Dataverse (`data.inrae.fr/api/datasets/:persistentId`). **Hypothèse invalidée**.

### Résultat brut

**0 paires retenues sur 36 DOIs candidats testés.** Tous 404 sur `data.inrae.fr`.

### Investigation

Résolution `https://doi.org/{doi}` sur un échantillon :

| DOI | Redirige vers |
|---|---|
| `10.17180/ciag-2024-vol94-art20` | `hal.inrae.fr/ARINRAE-INNOVAGRO/hal-04623296` |
| `10.17180/novae-2023-no-art02` | `revue-novae.fr/article/view/9070` |
| `10.14758/m20h-1q76` | `hal.inrae.fr/hal-02986866` |
| `10.15454/3q89-7f93` | `hal.inrae.fr/ARINRAE-INNOVAGRO/hal-03231711` |

Le client DataCite `inist.inra` ne distribue **pas de datasets Dataverse** sur ces préfixes — il enregistre des DOIs qui pointent en majorité vers **HAL-INRAE** (instance HAL institutionnelle) et marginalement vers des revues OJS isolées (Novae, etc.).

### Lecture

- Les publications HAL-INRAE sont **déjà couvertes par notre extracteur HAL** (qui collecte tout HAL via `hal.archives-ouvertes.fr` et ses miroirs institutionnels). Ingérer ces DOIs via DataCite serait redondant.
- Les publications de revues niches (Novae, etc.) sont **inaccessibles par API native** : OJS individualisé par revue, pas d'API biblio mutualisée. DataCite est la seule porte d'entrée centralisée.
- Le préfixe `inist.inra` n'est donc pas un proxy d'un repository unique, c'est un **enregistreur de DOIs pour le périmètre INRA/INRAE**, hétérogène par construction.

## Discovery par affiliation UCA (suite du spike)

Spike complémentaire `interfaces/cli/oneshot/datacite_affiliation_discovery_spike.py`. Question : `api.datacite.org/dois?query=…` permet-il de retrouver des publications UCA via leur affiliation textuelle, indépendamment d'un DOI déjà en staging ? Hypothèse de cadrage initiale du chantier (*« DataCite n'a pas d'index affiliation/ROR exploitable »*) qu'on cherche à vérifier — c'était une assertion non-mesurée.

### Variantes testées

| Query | Total hits |
|---|---:|
| `creators.affiliation.name:"Université Clermont Auvergne"` | **2 298** |
| `contributors.affiliation.name:"Université Clermont Auvergne"` | 1 294 |
| Recherche libre `Université Clermont Auvergne` (tous champs) | 1 320 |

`creators.affiliation.name` (phrase quoted) ressort comme la plus complète. Les phrase queries d'Elasticsearch matchent la sous-chaîne au sein d'affiliations composées (« Université Clermont Auvergne, CNRS, Institut Pascal, Clermont-Ferrand, France ») sans avoir besoin d'égalité stricte.

### Diff avec la base de publications UCA

- **2 298 DOIs DataCite trouvés** via `creators.affiliation.name`
- **376 déjà en base** (16.4 %)
- **1 922 nouveaux candidats** (83.6 %) — invisibles dans HAL / OpenAlex / WoS / scanR avec le périmètre actuel

Distribution des 1 922 nouveaux candidats par préfixe (top 10) :

| Préfixe | Client DataCite | Nouveaux |
|---|---|---:|
| 10.15454 | INRAE | 860 |
| 10.5281 | Zenodo (CERN) | 457 |
| 10.57745 | Recherche Data Gouv France | 240 |
| 10.7910 | Harvard Dataverse | 140 |
| 10.60692 | OpenAlex « Greater South Information System » | 44 |
| 10.35003 | (à investiguer) | 23 |
| 10.4230 | Schloss Dagstuhl | 22 |
| 10.18145 | (à investiguer) | 20 |
| 10.57837 | ACTRIS-ARES Data Portal | 17 |
| 10.48579 | data.InDoRES | 16 |

### Lecture

L'hypothèse initiale « DataCite reste DOI-driven » est **fausse**. L'API expose un index affiliation exploitable, et le volume retourné (~2 300 publications UCA dont 84 % nouvelles pour nous) est largement significatif. DataCite devient une **source d'extraction de plein droit** — à mettre au même niveau que HAL, OpenAlex, scanR, WoS — pas un simple fallback DOI-driven.

Notable :
- **INRAE (10.15454) : 860 DOIs nouveaux.** Confirme que l'extracteur HAL n'attrape pas tout INRAE (contrairement à ce que suggérait le sample de 4 DOIs de la section précédente). L'apport biblio est massif.
- **Zenodo (10.5281) : 457 DOIs nouveaux.** Datasets, software, preprints UCA invisibles côté HAL/OpenAlex.
- **Recherche Data Gouv (10.57745) : 240.** Plateforme nationale dataset, en croissance.

## Discovery par affiliation côté Crossref (suite)

Même question que pour DataCite, transposée à Crossref. Spike `interfaces/cli/oneshot/crossref_affiliation_discovery_spike.py`. Endpoint `api.crossref.org/works?query.affiliation=…` (substring/word match Elasticsearch). Filtre années 2020-2026.

**NB** : diff mesuré sur la base locale de cette session, **pas la base de prod**. Le chiffre de « nouveaux candidats » est indicatif et doit être recalculé sur prod pour le vrai delta.

### Volumes

| Mesure | Valeur |
|---|---:|
| Total annoncé par Crossref (`meta.total-results`) pour la query + filtre | 237 847 |
| Paginé pour le spike (cap 30 pages × 1 000) | 30 000 |
| Déjà en base locale | 5 649 (18.8 %) |
| Nouveaux candidats (base locale) | 24 351 (81.2 %) |

### Top préfixes des nouveaux candidats (base locale)

10.1080 (Taylor & Francis, 1 695), 10.1002 (Wiley, 1 595), 10.21203 (Research Square preprints, 1 401), 10.3390 (MDPI, 1 242), 10.7202 (Érudit Canada, 1 201), 10.1111 (Wiley, 1 068), 10.1093 (Oxford UP, 1 013), 10.1021 (ACS, 923), 10.1103 (APS, 891), …

Plus un préfixe surprise `10.64628` avec 2 128 nouveaux candidats — à investiguer (peut-être un éditeur récent ou un préfixe à forte présence de faux positifs).

### Lecture

Crossref est exploitable affiliation-driven. **Mon assertion précédente (« on a peut-être conclu un peu vite ») était justifiée — c'est en effet exploitable, comme DataCite.**

Deux nuances :

1. **Volume gonflé par les faux positifs.** Crossref retourne 237 847 hits avec un ranking par pertinence. Le matching ES sur tokens (Université, Clermont, Auvergne) ramène très probablement des publis non-UCA (autres « Université », autres « Clermont », autres « Auvergne ») au fur et à mesure que la relevance baisse. Cap raisonnable à arbitrer.

2. **L'overlap avec la base **chute** quand on plonge plus loin dans le ranking.** Sur le top 2 000 (sorted par relevance), 97.8 % d'overlap (déjà en base). Sur 30 000 paginés, overlap tombé à 18.8 %. Donc soit Crossref a beaucoup de matches que les autres sources (OpenAlex, HAL) n'ont pas captés, soit ce sont des faux positifs au-delà du top. À vérifier au lancement réel (échantillonnage qualité sur quelques DOIs de la queue).

### Implications pour Phase 3

- Crossref affiliation-driven est donc à mettre **en parallèle de DataCite affiliation-driven**, pas en alternative. Les deux sont complémentaires : Crossref couvre la littérature publiée chez les éditeurs classiques (Wiley, T&F, MDPI, Springer, etc.), DataCite couvre les datasets, preprints, theses, repositories.
- Architecture cible : **deux extracteurs affiliation-driven supplémentaires** (`infrastructure/sources/crossref/` et `infrastructure/sources/datacite/`), exposant chacun un mode de fetch par affiliation analogue à `fetch_uca_publications` de HAL/OpenAlex.
- La cible UI évoquée (icônes Crossref + DataCite comme registry du DOI à côté des sources d'extraction) devient particulièrement cohérente : 6 sources d'extraction (HAL, OpenAlex, scanR, WoS, Crossref, DataCite) + 2 registries du DOI (Crossref, DataCite) à distinguer dans la cellule « Sources ».

## Synthèse — décision à prendre

Le spike a réfuté **deux hypothèses cadres** du chantier initial :

1. **Sur Zenodo** : DataCite est **au moins aussi riche que l'API native** sur les champs biblio. Écrire un extracteur Zenodo natif n'apporterait que les fichiers / stats détaillées, hors périmètre. Pas de motif d'investir dans un extracteur Zenodo natif.

2. **Sur INRAE** : l'API « native » Dataverse n'est pas applicable au préfixe `inist.inra`. Les DOIs redirigent vers HAL-INRAE ou vers des revues OJS isolées. *Mais* (point 3 ci-dessous) l'extracteur HAL n'attrape pas tout INRAE — DataCite ramène 860 DOIs INRAE absents de la base.

3. **DataCite est exploitable affiliation-driven** : `creators.affiliation.name:"Université Clermont Auvergne"` retourne 2 298 publications UCA, dont 1 922 (84 %) absentes de la base locale.

4. **Crossref aussi est exploitable affiliation-driven** : `query.affiliation=Université Clermont Auvergne` (filtre 2020-2026) retourne 237 847 hits avec ranking par pertinence. Sur les 30 000 plus pertinents paginés, 24 351 absents de la base locale (81 %). Volume total à pondérer (faux positifs probables au-delà du top de la relevance).

**Implications pour Phase 3** : le périmètre originel (« extracteur DataCite DOI-driven via `fetch_missing_doi` ») doit être complètement réécrit. L'objectif devient **deux extracteurs affiliation-driven supplémentaires** — `infrastructure/sources/crossref/` et `infrastructure/sources/datacite/` — exposant chacun un fetch par affiliation analogue à `fetch_uca_publications` côté HAL/OpenAlex/scanR/WoS. Le mode DOI-driven existant côté Crossref (via `fetch_missing_doi`) reste utile en complément (un DOI apporté par une autre source mais que la query affiliation n'a pas attrapé).

Points à arbitrer ouverts :

1. **Recalculer les deltas sur la base de prod**. Les 84 % (DataCite) et 81 % (Crossref) sont mesurés sur la base locale de cette session, qui n'est pas représentative. Le vrai signal métier sortira d'une rejouée sur prod.

2. **Crossref : où on cape la pagination ?** 237k hits totaux dont la queue est probablement bruyante (faux positifs token-match). Échantillonner la qualité sur les pages tardives avant de fixer un cap.

3. **DataCite : `creators` seul ou `creators + contributors` ?** Volumes 2 298 vs union estimée ~2 500-2 800.

4. **Stratégie d'ingestion** : full sweep périodique (comme HAL/OpenAlex) ou incremental via date `updated` ? DataCite et Crossref supportent tous deux le filtrage incrémental sur `updated`.

5. **`doc_type` mapping DataCite** : à finaliser au moment de coder le normalizer.

6. **Préfixe Crossref `10.64628`** (2 128 nouveaux candidats, top 1 de la longue traîne) : à investiguer — sans doute un éditeur ou une plateforme à identifier.
