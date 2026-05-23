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

## Synthèse — décision à prendre

Le spike apporte deux signaux nets.

**Sur Zenodo** : DataCite est **au moins aussi riche que l'API native** sur les champs biblio. Écrire un extracteur Zenodo natif n'apporterait que les fichiers / stats détaillées, hors périmètre. **Pas de motif d'investir dans un extracteur Zenodo natif.**

**Sur INRAE** : l'API « native » n'existe pas comme entité unique. Les DOIs `inist.inra` redirigent soit vers HAL (couvert), soit vers des revues OJS isolées (non couvert centralement). **Pas d'API native à comparer ; le débat se réduit à : DataCite pour ce qui n'est pas déjà dans HAL, ou rien.**

Par extrapolation prudente aux 99 autres clients DataCite rencontrés sur le corpus UCA (longue traîne à 1 préfixe chacun, cf. spike Phase 0) : écrire un extracteur natif par repository est intenable, et la qualité DataCite démontrée sur Zenodo (le client le mieux outillé) est un bon indicateur de plafond.

**Lecture pour la décision Phase 3** : option « DataCite seul » à favoriser. Reste à arbitrer :

1. **Faut-il ingérer DataCite pour les DOIs déjà couverts par HAL ?** Soit (i) on filtre côté `get_cross_import_dois("datacite")` pour exclure les DOIs déjà présents en `source_publications` via la source `hal`, soit (ii) on ingère tout et la consolidation cross-source absorbe la redondance via `SOURCE_PRIORITY`. Option (ii) plus simple, option (i) plus économe en appels API.

2. **Exclusions explicites côté `get_cross_import_dois("datacite")`** : préfixe `10.60692` (DOIs OpenAlex synthétiques, déjà acté Phase 0). Faut-il en ajouter d'autres maintenant qu'on connaît mieux la longue traîne ?

3. **Mapping `doc_type` DataCite** (déjà ouvert en fiche). À finaliser au moment de l'écriture du normalizer DataCite.
