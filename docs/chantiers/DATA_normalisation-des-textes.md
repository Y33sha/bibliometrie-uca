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

- [ ] Inventaire des sites d'écriture de chaque colonne, pour recalculer chaque valeur avec la fonction du pipeline.
- [ ] Recalcul des lignes qui contiennent une écriture non latine. Identités d'auteur : clé recalculée, identités en collision fusionnées.
- [ ] Mesure : titres, noms et adresses dont la forme normalisée change ; publications et personnes dont le matching change.

### 3. Unicité des adresses

- [ ] Fusion des jumelles : signatures, ROR et liens aux structures rattachés à l'adresse conservée.
- [ ] Contrainte d'unicité sur la forme normalisée. Écriture des adresses par cette clé.
- [ ] Formes normalisées vides écartées à la normalisation.

### 4. Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Pays des jumelles divergents.** La fonction de préséance du chantier `DATA_pays-des-signatures.md` les départage. La fusion peut attendre cette fonction, ou garder provisoirement l'union des pays.
- **Texte brut conservé à la fusion.** Les signatures affichent le texte brut de l'adresse conservée : la première insérée, ou la plus fréquente.
- **Décision contradictoire.** Le groupe de jumelles aux décisions opposées se tranche à la main.
