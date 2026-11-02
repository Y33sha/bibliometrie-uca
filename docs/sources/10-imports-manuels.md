# Imports manuels

*À jour le 2026-11-02.*

## Extraction RH

`uv run python -m interfaces.cli.imports.import_persons <fichier>` importe un export RH, CSV ou TSV :

- `hr_records` : une fiche par personne, avec matricule, email, catégorie de personnel, statut, corps et grade ;
- `hr_periods` : périodes de présence dans une unité. Une unité reconnue dans `structures` reçoit son `structure_id`.

Un agent se rattache à sa fiche par son matricule, à défaut par son email, à défaut à l'unique homonyme sans fiche RH. Sinon, l'import crée la personne. Le nom d'une personne en base reste inchangé. Sur la fenêtre d'observation de l'export, l'export fait foi, et les périodes antérieures sont conservées. L'import refuse un export antérieur au dernier importé.

Les personnes présentes dans la base RH sont marquées d'une coche dans la [liste des personnes](../guide-utilisateur/pages-publiques/04-personnes.md#liste-persons). Une personne avec une fiche RH est toujours conservée par une fusion.

## Données APC

`uv run python -m interfaces.cli.imports.import_apc <fichier>` importe un fichier de frais de publication dans `apc_payments`. Le script reconnaît trois formats à leurs colonnes :

- le jeu de données [OpenAPC](../glossaire.md#openapc), fichier brut [`apc_de.csv`](https://github.com/OpenAPC/openapc-de/blob/master/data/apc_de.csv) : frais d'open access déclarés par les établissements participants ;
- le fichier « frais hors OA » de l'enquête nationale : autres frais de publication ;
- la réponse d'un établissement à l'enquête APC. Un montant négatif y annule un paiement.

Le script importe les paiements rattachés par DOI à une publication de la base. Avec `--institution`, il importe aussi les paiements à DOI de l'établissement absents de la base, qui rejoignent leur publication quand elle entre dans la base. L'établissement se désigne par son nom (OpenAPC), son `coman_id` (frais hors OA) ou son ROR (réponse à l'enquête). Un réimport ne crée pas de doublon.

La colonne `institution` désigne le payeur. Le laboratoire et le payeur sont rattachés à leur structure par les formes de noms ; le script liste les libellés sans structure. La réponse d'un établissement l'emporte sur OpenAPC, qui reprend les réponses à l'enquête sous une forme variable.

OpenAPC recense seulement les paiements des établissements participants : les paiements d'autres payeurs y sont incomplets. Le filtre APC et la mesure « Montant des APC » retiennent donc les seuls paiements de l'établissement.

