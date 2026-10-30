# Imports manuels

*À jour le 2026-09-07.*

## Extraction RH

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/imports/import_persons.py) → table `hr_records`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin;
- Rattaché à une personne du référentiel via `hr_records.person_id`;
- Les personnes présentes dans la base RH se filtrent et sont marquées d'une coche dans la [liste des personnes](../guide-utilisateur/pages-publiques/04-personnes.md#liste-persons).

Le département RH est affiché pour information. Les liens entre personnes et structures viennent des [contributions](../glossaire.md#contribution).

L'import crée la personne et sa fiche RH. La fiche enrichit la personne, et une personne avec une fiche RH est toujours conservée par une fusion.

## Données APC

`uv run python -m interfaces.cli.imports.import_apc <fichier>` importe un fichier de frais de publication dans `apc_payments`. Le script reconnaît trois formats à leurs colonnes :

- le jeu de données [OpenAPC](../glossaire.md#openapc), fichier brut [`apc_de.csv`](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) : frais d'open access déclarés par les établissements participants ;
- le fichier « frais hors OA » de l'enquête nationale : autres frais de publication ;
- la réponse d'un établissement à l'enquête APC. Un montant négatif y annule un paiement.

Le script importe les paiements rattachés par DOI à une publication de la base. Avec `--institution`, il importe aussi les paiements à DOI de l'établissement absents de la base, qui rejoignent leur publication quand elle entre dans la base. L'établissement se désigne par son nom (OpenAPC), son `coman_id` (frais hors OA) ou son ROR (réponse à l'enquête). Un réimport ne crée pas de doublon.

La colonne `institution` désigne le payeur. Le laboratoire et le payeur sont rattachés à leur structure par les formes de noms ; le script liste les libellés sans structure. La réponse d'un établissement l'emporte sur OpenAPC, qui reprend les réponses à l'enquête sous une forme variable.

OpenAPC recense seulement les paiements des établissements participants : les paiements d'autres payeurs y sont incomplets. Le filtre APC et la mesure « Montant des APC » retiennent donc les seuls paiements de l'établissement.

