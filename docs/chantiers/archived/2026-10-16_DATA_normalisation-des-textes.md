# Chantier — Normalisation des textes : écritures non latines et unicité des adresses

## Contexte

`normalize_text` (`domain/normalize.py`) prépare un texte pour le dédoublonnage et le matching : balises, casse et diacritiques retirés, puis tout caractère hors `[a-z0-9]` remplacé par un espace. La fonction SQL `normalize_name_form()` est son équivalent. Un test vérifie leur alignement (`tests/integration/test_normalize_alignment_python_sql.py`).

Le remplacement hors `[a-z0-9]` efface les écritures non latines. Des textes distincts deviennent égaux :

- adresses : 13 adresses en japonais ou en russe ont une forme normalisée vide ;
- titres : 75 notices sources ont un titre normalisé vide, 203 ont un titre en écriture non latine ;
- noms : 227 identités d'auteur ont un nom normalisé vide, pour 1 058 signatures.

Colonnes stockées issues de cette normalisation :

| Table | Colonnes |
|---|---|
| `source_publications`, `publications`, `journals`, `monographs` | `title_normalized` |
| `author_identifying_keys` | `last_name_normalized`, `first_name_normalized`, `author_name_normalized`, `key_hash` |
| `persons` | `last_name_normalized`, `first_name_normalized` |
| `person_name_forms` | `name_form` |
| `subjects` | `label_normalized` |
| `publishers`, `doi_prefixes` | `name_normalized`, `publisher_name_normalized`, `client_name_normalized` |
| `journal_name_forms`, `publisher_name_forms`, `language_forms`, `place_name_forms` | `form_normalized` |
| `addresses` | `normalized_text` |

`addresses` est unique par texte brut. Des textes qui diffèrent par la ponctuation, la casse ou les accents donnent des lignes distinctes de même forme normalisée : 592 507 adresses pour 509 522 formes normalisées. Chaque jumelle reçoit ses structures et son pays séparément. 1 534 groupes de jumelles ont des pays différents. Dans un groupe, l'administration a confirmé un lien sur une jumelle et l'a infirmé sur l'autre. 35 adresses ont une forme normalisée vide.

## Décisions

**Écritures non latines conservées.** `normalize_text` garde les lettres et les chiffres de toutes les écritures. La ponctuation et les symboles deviennent des espaces. La règle vaut pour les titres, les noms et les adresses.

**Diacritiques retirés sur les lettres latines et grecques.** é → e, ά → α, ё → е. Les autres marques restent : が reste が, й reste й.

**Normalisation calculée seulement en Python.** La fonction SQL est supprimée : les classes de caractères de PostgreSQL coupent les mots des écritures indiennes au virama, et ses regex ignorent les marques Unicode.

**Une adresse par forme normalisée.** La forme normalisée est la clé d'unicité de `addresses`. Un texte brut se rattache à l'adresse de même forme normalisée. Un texte de forme normalisée vide est écarté.

## Phasage

### 1. Fonctions de normalisation

- [x] `normalize_text` : écritures non latines conservées, diacritiques retirés sur les lettres latines et grecques.
- [x] Fonction SQL `normalize_name_form()` et test d'alignement supprimés. Les formes de noms des personnes arrivent normalisées par Python. La recherche dans les sujets lit `subjects.label_normalized`, indexée en trigram.

### 2. Valeurs stockées

- [x] Inventaire des sites d'écriture de chaque colonne, et script de recalcul (`interfaces/cli/oneshot/recompute_normalized_texts.py`). Les formes de noms des structures, des lieux et des langues sont saisies sans texte source et restent en l'état.
- [x] Recalcul des formes stockées (`recompute_normalized_texts`). Identités d'auteur : clé recalculée, identités en collision fusionnées.
- [x] Mesure, 2026-10-16 : 643 titres de notices sources, 1 338 titres de publications et 759 adresses changent de forme normalisée. 267 signatures changent d'identité d'auteur, 342 identités orphelines sont purgées.

### 3. Unicité des adresses

- [x] Fusion des jumelles (`interfaces/cli/oneshot/merge_address_twins.py`) : l'adresse la plus citée réunit les signatures, ROR, liens aux structures et pays de ses jumelles ; des décisions opposées redeviennent à examiner ; les formes vides sont supprimées. Le script refuse de tourner sur des formes périmées.
- [x] Contrainte d'unicité sur la forme normalisée, forme vide refusée (migration `3458e6b6593b`). Écriture des adresses par cette clé, formes vides écartées. La recopie des pays vers les jumelles disparaît.
- [x] Application, 2026-10-16 : `recompute_normalized_texts`, `merge_address_twins` (83 129 jumelles fondues dans 61 960 adresses, 22 formes vides supprimées), migration `3458e6b6593b`, puis `run_pipeline --from affiliations`.

### 4. Fin de chantier

- [x] Mise à jour de la documentation : cycle de vie des adresses (`docs/agregats/addresses.md`, 7e757a35f).
