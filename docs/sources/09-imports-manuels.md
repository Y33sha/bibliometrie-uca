# Imports manuels

## <span id="donnees-rh"></span>Base RH (personnel UCA)

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/imports/import_persons.py) → table `persons_rh`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin;
- Rattaché à une personne du référentiel via `persons_rh.person_id`;
- Sert de filtre dans la [liste des personnes](../guide-utilisateur/01-pages-publiques.md#liste-persons) (filtre "Base RH") et permet d'afficher une *blue checkmark* sur les personnes concernées.

Données fournies datées du 15/12/2025. La date est documentée dans la colonne `hr_export_date`. Cette extraction contient uniquement les **enseignants-chercheurs UCA**: pas les chercheurs CNRS, Inrae, etc., ni les personnels BIATSS UCA.

L'**affiliation** renseignée dans cette source est une chaîne de caractères (`UFR Médecine Pr Paramédic`, `IUT Info 43`) qui ne permet pas un mapping avec les laboratoires. Elle est affichée pour information, mais ne sert pas à créer les liens personne-structure dans l'appli. Les **liens personne-structure** dépendent des [*authorships*](../glossaire.md#authorship).

La [création de personnes](../pipeline/08-persons.md) se fait via les authorships des publications, indépendamment de l'existence d'une entrée `person_rh`.
La FK sur la table `person_rh` permet:
- d'enrichir les données sur les personnes;
- d'empêcher la suppression de ces personnes lors de fusions de doublons.

## <span id="donnees-apc"></span>Données APC

Données datées du 11/03/2026.

Fichier CSV importé via `python -m interfaces.cli.imports.import_apc` → table `apc_payments`.
- Contient : DOI, montant en €, éditeur, labo payeur, année
- Rattaché aux publications par DOI et aux structures par nom

**Incomplet**. Cette extraction ne contient pas les APC payés après 2024, et contient des trous dans la colonne DOI.

Complété par une extraction des [raw data](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) de [OpenAPC](../glossaire.md#openapc). (OpenAPC ne propose pas d'API.) Quelques manques ont été comblés, mais les données s'arrêtent aussi en 2024.

https://treemaps.openapc.net/apcdata/clermont-u/

## <span id="doaj"></span>DOAJ — bootstrap CSV

Le flux régulier passe par l'API DOAJ (cf. [08-sources-supplementaires.md#doaj](08-sources-supplementaires.md#doaj)). L'import CSV reste utilisable pour un bootstrap rapide depuis un dump complet (~21 k revues, plus rapide qu'un fetch unitaire).

Dump téléchargé manuellement depuis https://doaj.org/csv puis importé via `python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_*.csv`.

Le format de stockage est identique au sub-step API → pas de conflit, les deux flux écrivent dans `journals.doaj_payload` aux mêmes clés CSV.

Différence opérationnelle : l'import CSV fait un reset global `is_in_doaj=FALSE` avant de re-marquer (CSV = source de vérité à l'instant T) ; le sub-step API est incrémental.
