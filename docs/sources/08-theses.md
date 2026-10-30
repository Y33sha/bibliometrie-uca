# theses.fr

*À jour le 2026-10-28.*

https://theses.fr/

Documentation API : https://theses.fr/api-doc/swagger-ui/index.html

theses.fr est le portail [ABES](../glossaire.md#abes) qui agrège les thèses françaises **soutenues** et **en préparation**.

## API utilisées

**API de recherche** (`https://theses.fr/api/v1/theses/recherche/`) — liste des thèses des établissements du périmètre.

- Sans identifiants d'accès
- Requête : `q=etabSoutenancePpn:(<PPN>)`, pagination par `debut` / `nombre`
- 500 résultats par page (max accepté par l'API), à 3 req/s (`MAX_PER_SECOND`, `pipeline/ingestion/api_params.py`)
- L'API ne filtre pas par année : le moissonnage retient les thèses soutenues dans la fenêtre d'années du run, et toutes les thèses en cours

**API de détail** (`https://theses.fr/api/v1/theses/these/<identifiant>`) — une thèse par son identifiant.

- Le moissonnage lit le détail des thèses absentes de `staging`. `fetch_stale` relit le détail des autres, `fetch_missing` cherche les thèses par NNT.
- `staging` contient le détail de chaque thèse.

## Données récupérées

- **Thèse** : identifiant ([NNT](../glossaire.md#nnt) pour les soutenues, id `sXXXXXX` pour les en cours), titres et résumés multilingues, langues, DOI éventuel (DOI ABES `10.70675/...` pour les thèses récentes), discipline, dates (soutenance, première inscription), école doctorale, partenaires de recherche (laboratoires), sujets auteur (multilingues), sujets [RAMEAU](../glossaire.md#rameau) (vocabulaire contrôlé de la BnF), statut (`soutenue` / `enCours`), cas de diffusion et accessibilité
- **Personnes** : auteur(s), directeur(s), rapporteur(s), membres et président du jury — chacun avec nom, prénom et PPN IdRef si présent.

## Exemple de payload

Détail de la thèse soutenue `2017CLFAC001`. `resumes` tronqués, `mapSujets` réduit à 2 entrées par langue.

```json
{
  "titrePrincipal": "Extraction de substances naturelles antalgiques à partir de plantes utilisées dans la pharmacopée traditionnelle au Mali",
  "nnt": "2017CLFAC001",
  "doi": "10.70675/4ae914bez6c20z4d69z8711zbf2ebeabd0ac",
  "numSujet": null,
  "dateSoutenance": "06/01/2017",
  "datePremiereInscriptionDoctorat": null,
  "discipline": "Chimie Organique",
  "titres": {
    "en": "Extraction of natural analgesic compounds from plants used in traditional medicine in Mali",
    "fr": "Extraction de substances naturelles antalgiques à partir de plantes utilisées dans la pharmacopée traditionnelle au Mali"
  },
  "resumes": {
    "en": "The present work deals with the isolation of analgesic secon… (tronqué)",
    "fr": "Le travail présenté dans ce manuscrit porte sur l’isolation … (tronqué)"
  },
  "etabSoutenance": { "ppn": "196200032", "nom": "Université Clermont Auvergne (2017-2020)", "type": null },
  "codeEtab": "CLFA",
  "etabCotutelle": [],
  "partenairesRecherche": [
    {
      "ppn": "16450916X",
      "nom": "Institut de Chimie de Clermont-Ferrand (Aubière, Puy-de-Dôme ; 2012-....)",
      "type": "Laboratoire"
    }
  ],
  "mapSujets": {
    "en": [
      { "keyword": "Natural substances", "type": "sujet", "query": "Natural substances" },
      { "keyword": "Phytochemistry", "type": "sujet", "query": "Phytochemistry" }
    ],
    "fr": [
      { "keyword": "Ethnopharmacologie -- Afrique", "type": "sujetsRameau", "query": "\"Ethnopharmacologie -- Afrique\" ET 029725437" },
      { "keyword": "Analgésie", "type": "sujetsRameau", "query": "\"Analgésie\" ET 027219046" }
    ]
  },
  "auteurs": [{ "ppn": "204179041", "nom": "Danton", "prenom": "Ombeline" }],
  "directeurs": [
    { "ppn": "159337321", "nom": "Chalard", "prenom": "Pierre" },
    { "ppn": "159138752", "nom": "Ducki", "prenom": "Sylvie" }
  ],
  "rapporteurs": [
    { "ppn": "07464999X", "nom": "Caldefie-Chézet", "prenom": "Florence" },
    { "ppn": "179241311", "nom": "Pichette", "prenom": "André" },
    { "ppn": "08113259X", "nom": "Chemat", "prenom": "Farid" }
  ],
  "membresJury": [
    { "ppn": "159337321", "nom": "Chalard", "prenom": "Pierre" },
    { "ppn": "159138752", "nom": "Ducki", "prenom": "Sylvie" },
    { "ppn": "145330168", "nom": "Gabant", "prenom": "Marion" }
  ],
  "presidentJury": { "ppn": "07464999X", "nom": "Caldefie-Chézet", "prenom": "Florence" },
  "ecolesDoctorales": [
    { "ppn": "148543901", "nom": "École doctorale des sciences fondamentales (Clermont-Ferrand)", "type": null }
  ],
  "langues": ["fr", "en"],
  "cas": "cas1",
  "accessible": "oui",
  "source": "star",
  "status": "soutenue",
  "isSoutenue": true
}
```

Le détail d'une thèse en cours a la même structure, avec `status: "enCours"`, `nnt: null`, `doi: null`, `cas: null`, et l'identifiant `sXXXXXX` dans `numSujet`.

## Particularités

### Thèses soutenues et en cours

Une thèse avec `dateSoutenance` est soutenue (`thesis`), sans elle en cours (`ongoing_thesis`). Une thèse en cours n'a ni NNT ni DOI : son identifiant theses.fr (`sXXXXXX`) sert de clé. L'année est celle de la soutenance, à défaut celle de la première inscription.

### Rôles

Les cinq champs de personnes (`auteurs`, `directeurs`, `rapporteurs`, `membresJury`, `presidentJury`) donnent des contributions sources. Leurs rôles sont `author`, `thesis_director`, `rapporteur`, `jury_member` et `jury_president`. Seuls les auteurs ont une position d'auteur. Une personne présente dans plusieurs champs a plusieurs rôles ; elle est reconnue par son PPN, à défaut par son nom et son prénom.

### Identifiants : PPN IdRef pour les personnes, NNT pour les thèses

Le PPN [IdRef](../glossaire.md#idref) d'une personne, identifiant de l'ABES partagé avec d'autres sources, sert de clé forte à la [résolution des personnes](../pipeline/09-persons.md).

Le NNT (ex. `2017CLFAC001`) est l'identifiant primaire de l'enregistrement source. HAL, OpenAlex et ScanR le donnent aussi : leurs enregistrements sources sont rattachés à la même publication.

### Affiliations partagées au document

L'établissement de soutenance (`etabSoutenance`) et les laboratoires partenaires (`partenairesRecherche`) sont des propriétés du document. La normalisation les garde dans `source_extras` avec leur PPN IdRef, et les contributions sources de la thèse sont sans adresse. La vue `source_contribution_structures` rattache toutes les contributions sources à l'établissement de soutenance quand son PPN figure parmi les établissements du périmètre, et la contribution source du doctorant à chaque laboratoire partenaire reconnu par son PPN (`idref_structures`).

### Statut open access

Le statut open access vient de la diffusion de la thèse. `cas` est le cas de diffusion STAR : cas 1 à 4, une version de la thèse est destinée à Internet ; cas 5 et 6, l'intranet de l'établissement seulement. `accessible` dit si la thèse est consultable.

| Diffusion | `oa_status` |
|---|---|
| `accessible` = `oui` | `green` |
| cas 1 à 4, `accessible` = `non` | `embargoed` |
| cas 5 ou 6, thèse en cours | `closed` |

### Langue et résumé

La langue est la première de `langues`. Le résumé est celui de la première langue qui en a un.
