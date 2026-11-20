# Structures, pays et périmètre des contributions sources

*À jour le 2026-11-20.*

## Référentiels ROR et HAL (`structure_referentials`)

- **`refresh_ror`** — importe la dernière version du dump ROR, publié sur Zenodo, si elle n'est pas déjà importée.

- **`refresh_hal_structures`** — charge depuis l'API HAL les structures citées par les contributions sources et absentes du référentiel `ref.hal_structures`, puis leurs parents.

## Affiliations (`affiliations`)

La phase rattache les contributions sources aux structures du périmètre, et marque leur entrée dans le périmètre.

- **`classify_addresses`** — pose l'origine du texte des adresses sans origine (`addresses.origin`). La première règle applicable décide :
   - « SIGLE - Nom (adresse postale - Pays) » : libellé HAL ;
   - crochets contenant une période, des lieux ou un nom de structure (« University of Mons [Belgium] ») : libellé HAL ;
   - texte égal au nom d'une structure HAL ou d'une organisation ROR, après normalisation : nom seul ;
   - « Nom, Pays », le nom étant celui d'une structure HAL sans ses crochets ou d'une organisation ROR : nom seul ;
   - texte avec virgule : adresse brute ;
   - texte terminé par un pays entre parenthèses : libellé HAL ;
   - texte terminé par un nom de pays : adresse brute ;
   - autre texte : nom seul.

- **`detect_concatenated_addresses`** — repère les adresses concaténées : plusieurs affiliations réunies dans un seul texte, chacune suivie des initiales de ses auteurs. Une adresse concaténée est sans indice de périmètre.

- **`resolve_addresses`** — cherche dans le texte de chaque adresse normalisée les formes de nom des structures (`structure_name_forms`). Le résultat est écrit dans `address_structures`, avec la forme de nom détectée. Les rattachements confirmés ou saisis à la main restent en place.

   Trois options des formes de nom limitent les faux positifs :
   - une forme courte ou marquée « mot entier » compte seulement entre deux caractères qui ne sont pas des lettres ;
   - une forme « à contexte requis » compte seulement si une autre structure de sa liste est reconnue dans l'adresse ;
   - une forme « excluante » empêche la reconnaissance de sa structure dans l'adresse qui la contient.

- **`resolve_thesis_partners`** — rattache le PPN IdRef de chaque laboratoire partenaire de thèse à une structure, par les formes de noms (`idref_structures`).

- **`decide_source_contribution_perimeter`** — rafraîchit la vue matérialisée `source_contribution_structures`, qui rattache chaque contribution source aux structures du périmètre atteintes, avec l'indice : adresse, ROR, structure HAL, établissement de soutenance ou laboratoire partenaire d'une thèse, déposant d'un brevet. Les adresses de la contribution source font autorité. Un ROR est un indice seulement pour une contribution source sans adresse. Une contribution source entre aussi dans le périmètre quand elle contient un identifiant fort (ORCID, IdRef, `hal_person_id`) d'une personne avec une fiche RH. Le document paraît alors pendant une présence continue de la personne dans l'établissement, de l'année qui suit son début à l'année de sa fin. Ces indices sont écrits dans `source_contributions.perimeter_evidence` ; `in_perimeter` est vrai pour au moins un indice. Un enregistrement source sans publication, avec une contribution source dans le périmètre, est signalé à la phase [`publications`](07-publications.md), qui crée sa publication.

## Pays (`countries`)

La phase associe des pays aux adresses et aux contributions sources, pour l'analyse des collaborations internationales. Seules les adresses et les contributions sources marquées sont retraitées.

- **Pays trouvés** (`detect_by_country_name`, `detect_by_place_name`). Chaque moyen de détection propose des pays pour une adresse (`address_country_candidates`) : pays donnés par OpenAlex et ScanR, nom de pays en fin d'adresse, noms d'institutions et de villes (`place_name_forms`), saisie manuelle.
- **Pays retenus** (`resolve_countries`). Une fonction de préséance du domaine (`domain/addresses/country_detection.py`) compose `addresses.countries` à partir des pays trouvés.
- **Report** (`refresh_source_record_countries`). Le pays d'une contribution source réunit les pays retenus de ses adresses et ceux de ses structures HAL. Quand ses adresses ne donnent aucun pays, il prend ceux de ses organisations ROR sans adresse. `source_records.countries` réunit les pays de ses contributions sources. La publication d'un enregistrement source aux pays modifiés entre dans la file de consolidation, qui recalcule `publications.countries`.
