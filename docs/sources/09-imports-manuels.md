# Imports manuels

## <span id="donnees-rh"></span>Base RH (personnel UCA)

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/imports/import_persons.py) → table `persons_rh`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin
- Rattaché à une personne du référentiel via `persons_rh.person_id`
- Sert de filtre dans l'annuaire personnes (filtre "Base RH")

Données fournies par la DPCG le 15/12/2025. La date est documentée dans la colonne `hr_export_date`. Cette extraction contient uniquement les **enseignants-chercheurs UCA**: pas les chercheurs CNRS, Inrae, etc., ni les personnels BIATSS UCA.

L'**affiliation** renseignée dans cette source est une chaîne de caractères (`UFR Médecine Pr Paramédic`, `IUT Info 43`) qui ne permet pas un mapping avec les laboratoires. Elle est affichée pour information, mais ne sert pas à créer les liens personne-structure dans l'appli. Les **liens personne-structure** dépendent des [*authorships*](../glossaire.md#authorship).

La [création de personnes](../pipeline/06-persons.md) se fait via les authorships des publications, indépendamment de l'existence d'une entrée `person_rh`.
La FK sur la table `person_rh` permet:
- d'enrichir les données sur les personnes;
- d'empêcher la suppression de ces personnes (lors de fusions ou de nettoyage en masse des personnes sans authorship UCA).

## <span id="donnees-apc"></span>Données APC

Données fournies par la Bibliothèque numérique le 11/03/2026.

Fichier CSV importé via `python -m interfaces.cli.imports.import_apc` → table `apc_payments`.
- Contient : DOI, montant en €, éditeur, labo payeur, année
- Rattaché aux publications par DOI et aux structures par nom

**Incomplet**. Cette extraction ne contient pas les APC payés après 2024, et contient des trous dans la colonne DOI.

A compléter par une extraction des [raw data](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) de [OpenAPC](https://treemaps.openapc.net/apcdata/clermont-u/). A ma connaissance OpenAPC ne propose pas d'API. **Fait: pas beaucoup mieux (les données s'arrêtent aussi en 2024)**

## <span id="doaj"></span>DOAJ

*À documenter.*
