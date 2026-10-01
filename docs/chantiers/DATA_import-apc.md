# Chantier — Import des paiements APC sans doublon

## Contexte

Deux scripts alimentent la table `apc_payments` :

- `interfaces/cli/imports/import_apc.py` charge l'enquête nationale sur les frais de publication. Elle comporte deux fichiers : les APC, et les frais de publication hors open access (« FP hors OA » : pages, soumission, figures en couleur, couverture…).
- `interfaces/cli/imports/import_openapc.py` charge un extrait du jeu de données Open APC.

Les chiffres ci-dessous viennent de la base locale.

**Le réimport vide la table.** `import_apc` commence par `TRUNCATE apc_payments`, puis recharge les deux fichiers de l'enquête. Le vidage emporte les lignes Open APC, et les rattachements aux structures (`budget_structure_id`, `lab_structure_id`). Aucun script n'écrit ces rattachements : ils ont été posés en SQL à la main. `import_openapc` écarte tout DOI déjà présent dans la table, quel que soit le payeur. Le résultat dépend donc de l'ordre des imports.

**Les DOI ne sont pas normalisés.** `import_apc` stocke le texte de la cellule, sauf « non identifié » et « na ». « inconnu » (88 lignes) et « pas de doi » (74) sont stockés comme DOI.

**Un DOI porte souvent plusieurs paiements légitimes.** 553 DOI ont plusieurs lignes :

| Cas | DOI |
|---|---|
| Payeurs différents (paiement partagé) | 122 |
| Même payeur, même fichier (couverture et figures en couleur…) | 172 |
| Même payeur, fichiers différents (APC et frais hors OA) | 259 |
| Dont lignes strictement identiques | 31 |

**Les lignes sans DOI sont nombreuses.** Le fichier APC de l'enquête en compte 1 452, toutes avec un titre. Le fichier FP hors OA en compte 5 322, et il n'a pas de colonne titre. Des lignes identiques y représentent des paiements distincts sans détail : « CNRS, 940 €, 2017, labo et revue non identifiés » revient 11 fois.

**Les frais hors OA comptent comme des APC.** Le total APC d'une publication additionne toutes ses lignes. Le filtre « avec APC » retient toute publication qui en a une.

**Open APC reprend l'enquête APC.** 23 616 lignes du jeu Open APC (dump d'octobre 2026) portent un DOI présent dans l'enquête en base. Sur 23 483 paires de même payeur, le montant est identique dans 23 450 cas : Open APC porte le montant HT de l'enquête.

**L'enquête porte surtout des paiements étrangers à la base.** Sur les 25 695 lignes du fichier APC, 723 ont un DOI de la base ; sur les 11 743 lignes des frais hors OA, 142. Pour les publications de la base, l'enquête apporte au-delà d'Open APC :

| Apport | Lignes |
|---|---|
| APC absents d'Open APC | 10 |
| APC présents dans Open APC sous un autre payeur | 3 |
| Frais hors OA à DOI de la base (absents d'Open APC) | 135 |
| Rattachements à un laboratoire (`lab_structure_id`), posés à la main | 204 APC, 89 frais hors OA |

Les 1 452 lignes APC sans DOI n'ont aucun titre identique à une publication de la base. Les 5 322 lignes de frais hors OA sans DOI n'ont pas de titre.

**`coman_id` identifie l'établissement payeur de l'enquête.** Chaque payeur a une valeur, commune aux deux fichiers, stable là où le texte varie : « CNRS » et « CNRS - Centre national de la recherche scientifique » partagent le 271. Aucun `coman_id` ne porte deux `budget_structure_id`.

**`source_file`** porte un libellé fixe pour l'enquête (`enquete_apc`, `fp_hors_oa`), le nom du fichier pour Open APC.

**Le code est dupliqué.** Deux `INSERT` écrivent la même table. Trois correspondances de colonnes décrivent le même paiement. Les conversions de montant et d'année suivent des règles différentes : un seul script borne l'année.

## Décisions

- **Deux sources disjointes.** Open APC fournit les frais d'open access ; le fichier « frais hors OA » de l'enquête, les autres frais de publication. Le fichier APC de l'enquête reste hors de la table.
- **Colonne `open_access_fee`** (booléen, non nul) : vrai pour une ligne Open APC, faux pour une ligne de frais hors OA.
- **Normaliser avant écriture.** Le DOI passe par `clean_doi`. Les valeurs de remplissage ne sont jamais écrites.
- **Un fichier CSV par import.** `source_file` porte le nom du fichier d'origine.
- **Réimport libre.** Un fichier se réimporte sans créer de doublon. La table n'est jamais vidée.
- **Périmètre** : les paiements dont le DOI est en base. Une étape ultérieure ajoute ceux de l'établissement, nommé en argument du script : Open APC le désigne par son nom, sans ROR ; le fichier hors OA, par son `coman_id`.
- **Rattachement aux structures par les formes de noms** (`structure_name_forms`), avec le matcher des adresses d'affiliation. Un libellé sans structure appelle une forme de nom.
  - Payeur (`budget_structure_id`) : le libellé `institution`, parmi les universités, écoles, organismes et CHU.
  - Laboratoire (`lab_structure_id`) d'un frais hors OA : le libellé `lab_name`, lu avec le payeur pour contexte, parmi les laboratoires.
  - Laboratoire d'un frais d'open access : déduit des auteurs correspondants de la publication.
- **Colonnes conservées** :
  - ce qui sert au rattachement et à son contrôle a posteriori : `lab_name`, `budget`, `institution`, `coman_id`, `issn`, `journal_name`, `publisher_name` ;
  - `journal_id` et `publisher_id`, pour des agrégats par revue ou par éditeur ;
  - `pub_year`, `billing_year` et `remarks`.
- **Colonnes supprimées** : `article_title`, `institution_type`, `all_surveys_answered`, `shared_payment`, `expense_type`, `publisher_type`, `journal_type`.
- **Index supprimés** : `idx_apc_billing_year` et `idx_apc_institution`, qu'aucune requête n'utilise.

## Phasage

### 1. DOI

- [x] `clean_doi` rejette les valeurs sans la forme `10.xxx/…` (`34c8257e3`).

### 2. Schéma

- [x] Migration : colonne `open_access_fee` ; suppression des colonnes et des index listés ; contrainte d'unicité.

### 3. Imports

- [x] Un seul script, `import_apc`, qui reconnaît le format du fichier à ses colonnes.
- [x] Import Open APC : tous les paiements à DOI de la base, sans écarter les DOI déjà présents ; insertion idempotente.
- [x] Import des frais hors OA : même mécanisme, sur le fichier de l'enquête.
- [x] DOI normalisé par `clean_doi`, journalisation par `infrastructure/observability/log.py`.
- [x] Tests : `tests/unit/interfaces/cli/imports/`, `tests/integration/cli/`.
- [ ] Reprise : réimport d'Open APC et des frais hors OA ; suppression des lignes du fichier APC de l'enquête.

### 4. Structures

- [x] Payeur et laboratoire des frais hors OA rattachés par les formes de noms, à chaque import ; le script liste les libellés sans structure.
- [ ] Formes de noms manquantes ajoutées d'après cette liste.
- [ ] Frais d'open access : laboratoire des auteurs correspondants.

### 5. Établissement

- [ ] Argument du script : l'établissement dont les paiements sont importés hors de la base.

### 6. Lectures et documentation

- [ ] Totaux et filtres : frais d'open access et frais hors OA distingués.
- [ ] `docs/sources/10-imports-manuels.md`, `docs/donnees/02-structures.md`, `docs/donnees/07-index-des-tables.md`.

## Questions ouvertes

- **Clé d'unicité des lignes hors OA sans DOI** (étape de l'établissement). Une ligne sans DOI n'a ni DOI ni titre : 11 paiements identiques de 940 € du CNRS en 2017 restent indiscernables. Le nom du fichier change d'une mise à jour à l'autre et ne peut pas entrer dans la clé. Proposition : contenu de la ligne et rang parmi les lignes identiques du fichier.
