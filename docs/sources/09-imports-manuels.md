# Imports manuels

## <span id="donnees-rh"></span>Base RH (personnel UCA)

Fichier CSV importé via [interfaces/cli/imports/import_persons.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/imports/import_persons.py) → table `persons_rh`.
- Contient : email, nom, prénom, département, rôle, dates de début/fin;
- Rattaché à une personne du référentiel via `persons_rh.person_id`;
- Sert de filtre dans la [liste des personnes](../guide-utilisateur/01-pages-publiques.md#liste-persons) (filtre "Base RH") et permet d'afficher une *blue checkmark* sur les personnes concernées.

Données fournies datées du 15/12/2025. La date est documentée dans la colonne `hr_export_date`. Cette extraction contient uniquement les **enseignants-chercheurs UCA**: pas les chercheurs CNRS, Inrae, etc., ni les personnels BIATSS UCA.

L'**affiliation** renseignée dans cette source est une chaîne de caractères (`UFR Médecine Pr Paramédic`, `IUT Info 43`) qui ne permet pas un mapping avec les laboratoires. Elle est affichée pour information, mais ne sert pas à créer les liens personne-structure dans l'appli. Les **liens personne-structure** dépendent des [*authorships*](../glossaire.md#authorship).

La [création de personnes](../pipeline/06-persons.md) se fait via les authorships des publications, indépendamment de l'existence d'une entrée `person_rh`.
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

## <span id="doaj"></span>DOAJ

Le [DOAJ](../glossaire.md#doaj) (Directory of Open Access Journals) maintient un dump CSV public de l'ensemble des journaux référencés (~21 k entrées). DOAJ expose aussi une API REST publique (https://doaj.org/api/v3), non utilisée pour l'instant.

Dump téléchargé manuellement depuis https://doaj.org/csv puis importé via `python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_*.csv`.

Données récupérées : payload CSV row complète stockée tel quel dans `journals.doaj_payload` (JSONB), avec `journals.is_in_doaj = TRUE` et `journals.doaj_imported_at` daté. Matching avec nos `journals` par **ISSN print ou electronic** : le script préfetche tous nos ISSN (`issn`, `eissn`, `issnl`) et fait le match en O(1).

Le CSV est **source de vérité** : à chaque import, `is_in_doaj` est d'abord remis à `FALSE` sur tous les journaux (un journal sorti du DOAJ entre deux dumps voit donc son flag basculer).

Utilisé en aval pour le badge DOAJ affiché sur les pages journaux et publishers.

*A compléter*
