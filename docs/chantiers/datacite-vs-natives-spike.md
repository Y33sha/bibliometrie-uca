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

## Synthèse — décision à prendre

Trois signaux nets, dont un qui change le paradigme initial.

**Sur Zenodo** : DataCite est **au moins aussi riche que l'API native** sur les champs biblio. Écrire un extracteur Zenodo natif n'apporterait que les fichiers / stats détaillées, hors périmètre. **Pas de motif d'investir dans un extracteur Zenodo natif.**

**Sur INRAE** : l'API « native » Dataverse n'est pas applicable au préfixe `inist.inra`. Les DOIs redirigent soit vers HAL-INRAE soit vers des revues OJS isolées. Pas d'API native unique à comparer. *Mais* (cf. ci-dessous), l'extracteur HAL n'attrape pas tout INRAE — la query DataCite par affiliation ramène 860 DOIs INRAE absents de la base.

**Sur la discovery par affiliation** : **changement de paradigme**. L'hypothèse cadre initiale « DataCite reste DOI-driven » est fausse. L'API DataCite expose un index `creators.affiliation.name` exploitable en phrase query, qui ramène 2 298 publications UCA, dont 1 922 (84 %) absentes de la base. DataCite devient une **source d'extraction de plein droit**, pas un fallback.

**Implications pour Phase 3** : le périmètre originel (« extracteur DataCite DOI-driven via `fetch_missing_doi` ») doit être réécrit. L'extracteur DataCite cible est **affiliation-driven** (comme HAL, OpenAlex, scanR), pas DOI-driven. Architecturalement :
- Une fonction de fetch initiale `fetch_uca_dois_from_datacite()` qui pagine `?query=creators.affiliation.name:"Université Clermont Auvergne"` et alimente staging.
- Plus la branche DOI-driven existante via `fetch_missing_doi --target datacite` pour les DOIs apportés par d'autres sources mais dont DataCite enrichit la métadonnée (notamment les preprints/datasets référencés via `relatedIdentifiers` côté Crossref).
- Le filtre `get_cross_import_dois("datacite")` reste pertinent pour le mode DOI-driven (avec ou sans exclusion `10.60692` — à arbitrer).

Trois points à arbitrer maintenant :

1. **Mode `creators.affiliation` seul ou union `creators + contributors` ?** `creators` = 2 298, `contributors` = 1 294, union probable ~2 500-2 800. Couvre-t-on uniquement les auteurs principaux ou aussi les contributeurs (techniques, méthodologiques) ?

2. **Stratégie d'ingestion** : full sweep périodique (comme HAL/OpenAlex aujourd'hui) ou incremental via `updated` date ? La query DataCite supporte `?query=… AND updated:[2026-05-01T00:00:00Z TO *]`.

3. **`doc_type` mapping DataCite** : à finaliser au moment de coder le normalizer (cf. spike Phase 0 sur la distribution `resourceTypeGeneral`).
