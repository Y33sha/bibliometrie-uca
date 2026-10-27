# Imports manuels

*À jour le 2026-09-07.*

## Extraction RH

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/imports/import_persons.py) → table `hr_records`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin;
- Rattaché à une personne du référentiel via `hr_records.person_id`;
- Sert de filtre dans la [liste des personnes](../guide-utilisateur/pages-publiques/04-personnes.md#liste-persons) (filtre "Base RH") et permet d'afficher une *blue checkmark* sur les personnes concernées.

Données fournies datées du 15/12/2025. La date est documentée dans la colonne `hr_export_date`. Cette extraction contient uniquement les **enseignants-chercheurs UCA**: pas les chercheurs CNRS, Inrae, etc., ni les personnels BIATSS UCA.

L'**affiliation** renseignée dans cette source est une chaîne de caractères (`UFR Médecine Pr Paramédic`, `IUT Info 43`) qui ne permet pas un mapping avec les laboratoires. Elle est affichée pour information, mais ne sert pas à créer les liens personne-structure dans l'appli. Les **liens personne-structure** dépendent des [*contributions*](../glossaire.md#contribution).

La [création de personnes](../pipeline/09-persons.md) se fait via les contributions des publications, indépendamment de l'existence d'une entrée `hr_records`.
La FK sur la table `hr_records` permet:
- d'enrichir les données sur les personnes;
- d'empêcher la suppression de ces personnes lors de fusions de doublons.

## Données APC

`python -m interfaces.cli.imports.import_apc <fichier>` importe un fichier de frais de publication dans `apc_payments`. Le script reconnaît trois formats à leurs colonnes :

- le jeu de données [OpenAPC](../glossaire.md#openapc), fichier brut [`apc_de.csv`](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) (OpenAPC ne propose pas d'API) : frais d'open access déclarés par les établissements participants ;
- le fichier « frais hors OA » de l'enquête nationale : autres frais de publication ;
- la réponse d'un établissement à l'enquête APC. Un montant négatif y annule un paiement.

Le script importe les paiements dont le DOI désigne une publication de la base. Avec `--institution`, il importe aussi les paiements à DOI de l'établissement absents de la base, qui rejoignent leur publication quand elle entre dans la base. L'établissement se désigne par son nom (OpenAPC), son `coman_id` (frais hors OA) ou son ROR (réponse à l'enquête). Un réimport ne crée pas de doublon.

La colonne `institution` désigne le payeur. Le laboratoire et le payeur sont rattachés à leur structure par les formes de noms ; le script liste les libellés sans structure. La réponse d'un établissement l'emporte sur OpenAPC, qui reprend les réponses à l'enquête sous une forme variable.

OpenAPC recense seulement les paiements des établissements participants : les paiements d'autres payeurs y sont incomplets. Le filtre APC et la mesure « Montant des APC » retiennent donc les seuls paiements de l'établissement.

