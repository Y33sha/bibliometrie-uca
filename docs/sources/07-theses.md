# theses.fr

https://theses.fr/

Documentation API : https://theses.fr/api-doc/swagger-ui/index.html

theses.fr est le portail [ABES](../glossaire.md#abes) qui agrège les thèses françaises **soutenues** et **en préparation**.

## API utilisée

**API de recherche** (`https://theses.fr/api/v1/theses/recherche/`) — moissonnage par établissement.

- Pas d'authentification
- Requête : `q=etabSoutenancePpn:(<PPN>)`, pagination par `debut` / `nombre`
- 500 résultats par page (max accepté par l'API), 0.3 s de délai entre requêtes

## Données récupérées

- **Thèse** : identifiant ([NNT](../glossaire.md#nnt) pour les soutenues, id `sXXXXXX` pour les en cours), titre (FR + EN), DOI éventuel (DOI ABES `10.70675/...` pour les thèses récentes), discipline, dates (soutenance, première inscription), école doctorale, partenaires de recherche (= laboratoires), sujets auteur (multilingues), sujets Rameau (vocabulaire contrôlé BNF), statut (`soutenue` / `enCours`)
- **Personnes** : auteur(s), directeur(s), rapporteur(s), examinateur(s), président de jury — chacun avec nom, prénom, PPN IdRef si présent, et l'intitulé de son rôle.

## Exemple de payload

Thèse soutenue `2022UCFAC034` (informatique, LIMOS). `sujets` réduits à 3 entrées FR + 3 EN, `sujetsRameau` réduit aux 2 premiers.

```json
{
  "id": "2022UCFAC034",
  "doi": "10.70675/406566ecz9cd7z41dbz8333zda4c1226764f",
  "nnt": "2022UCFAC034",
  "status": "soutenue",
  "sujets": [
    { "langue": "fr", "libelle": "Techniques asymétriques (clés publiques)" },
    { "langue": "fr", "libelle": "Sécurité de protocoles" },
    { "langue": "fr", "libelle": "Modèle calculatoire" },
    { "langue": "en", "libelle": "Public key (asymmetric) techniques" },
    { "langue": "en", "libelle": "Security protocols" },
    { "langue": "en", "libelle": "Computational model" },
    { "...": "(10 autres en fr + 12 autres en en)" }
  ],
  "auteurs": [
    { "nom": "Robert", "ppn": "26761991X", "prenom": "Léo" }
  ],
  "titreEN": "Design and analysis of provably secure protocols : Applications to messaging and attestation",
  "president": { "nom": "Pointcheval", "ppn": "111645751", "prenom": "David" },
  "directeurs": [
    { "nom": "Lafourcade", "ppn": "109895355", "prenom": "Pascal" },
    { "nom": "Onete", "ppn": "22090216X", "prenom": "Maria Cristina" }
  ],
  "discipline": "Informatique",
  "rapporteurs": [
    { "nom": "Nguyen", "ppn": "07790821X", "prenom": "Benjamin" },
    { "nom": "Önen", "ppn": "110910850", "prenom": "Suna Melek" }
  ],
  "examinateurs": [
    { "nom": "Bhargavan", "ppn": "198350155", "prenom": "Karthikeyan" },
    { "nom": "Dumas", "ppn": "11175786X", "prenom": "Jean-Guillaume" },
    { "nom": "Sanders", "ppn": "234066245", "prenom": "Olivier" }
  ],
  "sujetsRameau": [
    { "ppn": "07706674X", "libelle": "Messageries instantanées" },
    { "ppn": "027798119", "libelle": "Mesures de sûreté" },
    "<… 1 autre sujet Rameau>"
  ],
  "dateSoutenance": "22/09/2022",
  "titrePrincipal": "Design and analysis of provably secure protocols : Applications to messaging and attestation",
  "ecolesDoctorale": [
    {
      "nom": "École doctorale des sciences pour l'ingénieur (Clermont-Ferrand)",
      "ppn": "075501341",
      "type": null
    }
  ],
  "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
  "etabSoutenancePpn": "252404955",
  "partenairesDeRecherche": [
    {
      "nom": "Laboratoire d'Informatique, de Modélisation et d'Optimisation des Systèmes",
      "ppn": "155645919",
      "type": "Laboratoire"
    }
  ],
  "datePremiereInscriptionDoctorat": null
}
```

Le payload d'une thèse en cours a la même structure, avec `status: "enCours"`, `nnt: null`, `doi: null`, `dateSoutenance: null` et `datePremiereInscriptionDoctorat` rempli. L'identifiant est de la forme `sXXXXXX`.

## Particularités

### Soutenue vs en cours : un seul flux, deux états

Le même endpoint renvoie les deux. La présence de `dateSoutenance` est le seul signal fiable pour distinguer :
- présent → `doc_type = "thesis"` (soutenue)
- absent → `doc_type = "ongoing_thesis"` (en cours)

Les thèses en cours n'ont ni NNT ni DOI ; leur identifiant theses.fr (`sXXXXXX`) sert seul de clé. L'année est dérivée par cascade `dateSoutenance > datePremiereInscriptionDoctorat`.

### 5 rôles dans une thèse, tous matérialisés comme authorships

`auteurs`, `directeurs`, `rapporteurs`, `examinateurs`, `president` sont tous transformés en `source_authorships`, chacun avec ses `roles` (`author`, `supervisor`, `reviewer`, `committee_member`, `committee_president`). Seuls les auteurs portent un `author_position` ; les autres rôles ont `author_position = NULL`.

Une personne qui apparaît dans plusieurs champs est dédupliquée et porte plusieurs rôles. Clé de déduplication : PPN si présent, sinon `(nom, prenom)`.

### Identifiants : PPN IdRef pour les personnes, NNT pour les thèses

Le PPN [IdRef](../glossaire.md#idref) est stocké dans `source_authorships.person_identifiers->>'idref'` lorsque présent — c'est l'identifiant ABES, partagé avec d'autres sources. Sert de clé de matching forte dans la phase [persons](../pipeline/08-persons.md) du pipeline.

Le NNT (ex. `2022UCFAC034`) sert d'identifiant cross-source pour la thèse : exposé via `external_ids.nnt` côté `source_publications`, il permet le rattachement à des `source_publications` HAL/OpenAlex/ScanR qui exposent aussi le NNT.

### Affiliations partagées au document

`partenairesDeRecherche` (= laboratoires d'accueil) sont des affiliations du document, pas par-personne. Le pipeline les lie à tous les `source_authorships` de la thèse via l'`AddressLinker`. C'est cohérent avec la réalité — une thèse est rattachée à un (parfois plusieurs) laboratoire, et toutes les personnes du jury et de l'encadrement opèrent dans ce contexte.

### OA = `closed` par défaut côté source

Le payload *theses.fr* n'expose aucun signal sur le statut OA, donc `source_publications.oa_status` est posé à `closed` par défaut en l'absence d'autres sources ([HAL](../glossaire.md#hal) principalement).
