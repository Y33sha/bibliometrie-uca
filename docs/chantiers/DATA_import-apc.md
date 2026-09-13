# Chantier — Import des paiements APC sans doublon

## Contexte

Deux scripts alimentent la table `apc_payments` :

- `interfaces/cli/imports/import_apc.py` charge l'enquête nationale sur les frais de publication. Elle comporte deux fichiers : les APC, et les frais de publication hors open access (« FP hors OA » : pages, soumission, figures en couleur, couverture…).
- `interfaces/cli/imports/import_openapc.py` charge un extrait du jeu de données Open APC.

Les chiffres ci-dessous viennent de la base locale.

**Le réimport vide la table.** `import_apc` commence par `TRUNCATE apc_payments`, puis recharge les deux fichiers de l'enquête. Le vidage emporte les lignes Open APC, et les rattachements aux structures (`budget_structure_id`, `lab_structure_id`). Aucun script n'écrit ces rattachements : ils ont été posés en SQL à la main. `import_openapc` écarte tout DOI déjà présent dans la table, quel que soit le payeur. Le résultat dépend donc de l'ordre des imports.

**Les DOI ne sont pas normalisés.** `import_apc` stocke le texte de la cellule, sauf « non identifié » et « na ». « inconnu » (88 lignes) et « pas de doi » (74) sont stockés comme DOI. `clean_doi` les accepte aussi : il ne contrôle pas la forme `10.xxx/…`.

**Un DOI porte souvent plusieurs paiements légitimes.** 553 DOI ont plusieurs lignes :

| Cas | DOI |
|---|---|
| Payeurs différents (paiement partagé) | 122 |
| Même payeur, même fichier (couverture et figures en couleur…) | 172 |
| Même payeur, fichiers différents (APC et frais hors OA) | 259 |
| Dont lignes strictement identiques | 31 |

**Les lignes sans DOI sont nombreuses.** Le fichier APC de l'enquête en compte 1 452, toutes avec un titre. Le fichier FP hors OA en compte 5 322, et il n'a pas de colonne titre. Des lignes identiques y représentent des paiements distincts sans détail : « CNRS, 940 €, 2017, labo et revue non identifiés » revient 11 fois.

**Les frais hors OA comptent comme des APC.** Le total APC d'une publication additionne toutes ses lignes. Le filtre « avec APC » retient toute publication qui en a une.

**Les montants Open APC sont TTC** (« Includes VAT », d'après le schéma de données Open APC). Ils sont rangés dans `amount_eur_ht` avec les montants HT de l'enquête.

**`coman_id` identifie l'établissement payeur de l'enquête.** Chaque payeur a une valeur, commune aux deux fichiers, stable là où le texte varie : « CNRS » et « CNRS - Centre national de la recherche scientifique » partagent le 271. Aucun `coman_id` ne porte deux `budget_structure_id`.

**`source_file`** porte un libellé fixe pour l'enquête (`enquete_apc`, `fp_hors_oa`), le nom du fichier pour Open APC.

**Le code est dupliqué.** Deux `INSERT` écrivent la même table. Trois correspondances de colonnes décrivent le même paiement. Les conversions de montant et d'année suivent des règles différentes : un seul script borne l'année.

## Décisions

- **Normaliser avant écriture.** Le DOI passe par `clean_doi`, qui rejette toute valeur sans la forme `10.xxx/…`. Les valeurs de remplissage ne sont jamais écrites.
- **Un fichier CSV par import.** `source_file` porte le nom du fichier d'origine.
- **Réimport libre.** N'importe quel fichier se réimporte, dans n'importe quel ordre, sans créer de doublon. La table n'est jamais vidée.
- **Un doublon n'est pas écrit**, plutôt qu'écarté à chaque lecture. Même article, même structure payeuse, même montant : doublon.
- **Colonnes conservées** :
  - ce qui sert au rattachement et à son contrôle a posteriori : `lab_name`, `budget`, `institution`, `coman_id`, `issn`, `journal_name`, `publisher_name` ;
  - `journal_id` et `publisher_id`, pour des agrégats par revue ou par éditeur ;
  - `article_title`, pour rapprocher par titre les paiements sans DOI ;
  - `pub_year`, pour départager un rapprochement par titre ;
  - `remarks`.
- **Colonnes supprimées** : `institution_type`, `all_surveys_answered`, `shared_payment`, `expense_type`.
- **Index supprimés** : `idx_apc_billing_year` et `idx_apc_institution`, qu'aucune requête n'utilise.
- **Un seul module d'import** : une correspondance de colonnes par format de fichier, une seule insertion.

## Phasage

### 1. DOI

- [ ] `clean_doi` rejette les valeurs sans la forme `10.xxx/…`. Mesurer l'effet sur les autres sources avant de fusionner.
- [ ] L'import normalise le DOI par `clean_doi`.

### 2. Schéma

- [ ] Migration : suppression des colonnes et des index listés ; colonne de source (enquête APC, enquête FP hors OA, Open APC) ; contrainte d'unicité sur la clé retenue.
- [ ] Reprise des lignes existantes : source et `source_file`.

### 3. Rattachements aux structures

- [ ] Les rattachements `budget_structure_id` et `lab_structure_id` survivent au réimport, selon le mécanisme retenu.
- [ ] Reprise des rattachements existants.

### 4. Import unique

- [ ] Un module, une commande : un fichier, son format, `source_file` égal au nom du fichier.
- [ ] Insertion idempotente (`ON CONFLICT DO NOTHING` sur la clé).
- [ ] Doublons entre sources non écrits : même article, même structure payeuse, même montant.
- [ ] Rattachement à la publication par DOI, et par titre et année pour les lignes sans DOI si ce rapprochement est retenu.
- [ ] Journalisation par `infrastructure/observability/log.py`.
- [ ] Tests : `tests/unit/interfaces/cli/imports/`, `tests/integration/cli/test_import_apc.py`.

### 5. Lectures et documentation

- [ ] Totaux et filtre APC selon la décision sur les frais hors OA.
- [ ] `docs/sources/10-imports-manuels.md`, `docs/donnees/02-structures.md`, `docs/donnees/07-index-des-tables.md`.

## Questions ouvertes

- **Clé des lignes sans article identifié.** La règle « même article, même structure payeuse, même montant » laisse indiscernables les 11 paiements identiques sans DOI ni titre. Proposition : source, contenu et rang d'occurrence de la ligne dans le fichier.
- **Structure payeuse.** Les payeurs absents du référentiel des structures (Aix-Marseille Université, Institut Pasteur, CEA…) n'ont pas de `budget_structure_id`. La règle de doublon compare-t-elle alors le `coman_id`, qu'Open APC ne fournit pas ?
- **HT et TTC.** Un même paiement a un montant HT dans l'enquête et TTC dans Open APC : « même montant » ne les rapproche jamais. Convertir à l'import, avec quel taux ? Ou comparer avec une tolérance ?
- **Frais hors OA.** Les sortir des totaux et du filtre APC, ou ventiler « APC » et « autres frais de publication » ?
- **Rattachements.** Proposition : une table de correspondance contrôlable (`coman_id` → structure payeuse, `lab_name` → laboratoire), que l'import réapplique à chaque ligne écrite.
- **Colonnes à trancher** : `billing_year` (totaux par année), `publisher_type` et `journal_type` (classement de l'enquête, que la base établit par ailleurs).
- **Rapprochement par titre** des 1 452 paiements sans DOI de l'enquête : dans ce chantier ou dans un chantier à part ?
