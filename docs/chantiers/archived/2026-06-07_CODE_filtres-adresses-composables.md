# Chantier — Filtres composables pour le repérage des adresses (admin)

Commencé et terminé le 2026-06-07

Issu d'un item TODO_LAURA (« interface de repérage des adresses : ajouter filtres sur la base des autres structures reconnues dans l'adresse => ça aidera au repérage des faux négatifs »).

## Contexte

La revue manuelle des affiliations se fait sur `admin/addresses` ([+page.svelte](../../interfaces/frontend/src/routes/admin/addresses/+page.svelte)), structure par structure. Pour une structure X sélectionnée, l'écran liste les adresses et leur lien à X (détecté / validé / rejeté), avec une barre de filtres : un dropdown structure (le scope), un dropdown `Détection` (tous/détecté/non détecté), un dropdown `Validation` (tous/non validé/relié/rejeté), et **un seul** prédicat texte (`contient`/`ne contient pas` + champ).

Repérer les **faux positifs** est facile : on parcourt les liens détectés pour X et on détache les faux. Repérer les **faux négatifs** est laborieux : il faut prendre toutes les adresses non reliées à X et y chercher à l'œil des chaînes susceptibles de matcher X, sans moyen de réduire le corpus.

Côté données, tout le nécessaire existe déjà. La table de jointure `address_structures` porte, **pour chaque adresse, l'ensemble des structures reconnues** (pas seulement le scope courant) : `matched_form_id` (NULL = non détecté) et `is_confirmed` (NULL = non validé / TRUE = relié / FALSE = rejeté). La requête de liste renvoie déjà ce tableau complet par adresse (`json_agg structures` dans [`PgAddressesQueries.list_addresses`](../../infrastructure/queries/api/addresses.py)). Le filtrage actuel n'exploite ce join que pour le scope unique (`ast_filter` sur `:sid`) et un `ILIKE`/`NOT ILIKE` unaccent sur `raw_text`.

Conséquence : « filtrer sur les autres structures reconnues » se ramène à des prédicats `EXISTS`/`NOT EXISTS` sur `address_structures` — **aucun changement de schéma**, c'est query + API + UI.

Modèle de référence : `addresses(id, raw_text, pub_count, …)`, `address_structures(address_id, structure_id, matched_form_id, is_confirmed)`, `structures(id, name, acronym, code, structure_type)`.

## Décisions

*(Conception validée avec Laura ; reste questionnable sur les détails d'implémentation listés en fin.)*

1. **Zone « Filtres » délimitée, à deux étages.** Une ligne fixe « structure étudiée » (le dropdown structure de scope + ses dropdowns `Détection` et `Validation`, inchangés) ; puis une **pile de prédicats empilables**, chacun supprimable (`×`), ajoutables via `+ Ajouter`, tous combinés en **ET**.
2. **`Détection`/`Validation` restent attachés à la seule structure étudiée.** Les prédicats empilés n'ont pas leur propre détection/validation : l'association à une autre structure s'exprime par un binaire reconnue/non reconnue (point 4).
3. **Prédicat Texte** : `[contient | ne contient pas]` + champ libre. Généralise le couple unique actuel, rendu empilable (`contient X` ET `ne contient pas Y` ET …). Conserve l'`unaccent` ILIKE actuel.
4. **Prédicat Structure reconnue, binaire et multi-structures.** Opérateur `[reconnue comme | non reconnue comme]` + **multi-sélection** de structures affichées en tags supprimables sur la même ligne. Pas de distinction détection auto vs validation manuelle — superflu et moins lisible pour ce besoin de réduction de corpus (un lien CNRS pending est déjà un bon signal). « Reconnue comme K » = lien **pending ou confirmé** (association vivante, non rejetée) ; « non reconnue » = pas de lien, ou lien rejeté.
   - **Sémantique multi-structures** : une ligne **positive** `reconnue comme [A, B]` = **OR** (reconnue comme au moins une de A, B) ; une ligne **négative** `non reconnue comme [A, B]` = **aucune** (ni A ni B) ; les lignes entre elles restent en **ET** (décision 1).
   - **Contrainte UI** : l'opérateur OR (positive) / « aucune » (négative) doit être **explicitement lisible** dans l'intitulé de la ligne (ex. « reconnue comme l'une de : » / « non reconnue comme aucune de : »), pas seulement déductible.
   - SQL pour une ligne, structures `{A, B}`, condition *reconnue* `R(K)` = `EXISTS (… structure_id = K AND ((matched_form_id IS NOT NULL AND is_confirmed IS NULL) OR is_confirmed = TRUE))` :
     - positive → `(R(A) OR R(B))`
     - négative → `(NOT R(A) AND NOT R(B))`
5. **Aucune migration.** Le tout est porté par `AddressListFilters` (liste de prédicats typés), un WHERE dynamique paramétré, un composant front « filter-builder », et la sérialisation des prédicats dans l'URL.
6. **Anti-doublon global sur les structures.** Le picker liste **toutes les structures, y compris la structure étudiée, moins celles déjà posées dans n'importe quel prédicat structure** (toutes lignes confondues). Tolérer la structure étudiée permet un filtre négatif sur elle (`non reconnue comme X`) ; le dédup global évite à la fois la redondance et la contradiction `reconnue comme X` + `non reconnue comme X`.
7. **Application live.** Pas de bouton « Appliquer » : la requête se relance à chaque ajout/modif de prédicat (ils s'ajoutent un par un, charge maîtrisée). Debounce conservé sur les champs texte.
8. **État URL en paramètres répétés** (lisibles, bookmarkables) : `text=contient:physique`, `text=ne_contient_pas:toulouse`, `struct=reconnue:123` / `struct=non_reconnue:123`. Restauration au montage.

Workflow faux négatifs visé : structure étudiée = X, `Détection = Non détecté`, `+ Structure : reconnue comme l'une de [UCA, CNRS]`, puis affinage `+ Texte : contient « physique »` / `ne contient pas « Toulouse »` — le corpus à éplucher fond de plusieurs milliers à quelques dizaines.

## Phasage

### Phase 1 — Backend : modèle de filtres + query

- [x] Étendre `AddressListFilters` : `search`/`search_mode` unique remplacés par des listes de prédicats Texte `(mode, terme)` et Structure `(operator, structure_ids[])` (`7e3fbf58`)
- [x] Prédicats typés (`TextPredicate`/`StructurePredicate`, dataclasses du port) parsés dans le router depuis les params répétés ; pas de `dict` brut (`7e3fbf58`)
- [x] WHERE dynamique dans `list_addresses` : `ILIKE`/`NOT ILIKE` par prédicat texte ; `EXISTS`/`NOT EXISTS` avec `structure_id = ANY(...)` par prédicat structure (le OR / « aucune » se réduit par De Morgan), paramétré, AND-combiné. Garde-fou « non détecté » levé par tout prédicat de réduction (`7e3fbf58`)
- [x] Index : `idx_addr_struct_filter` `(structure_id, address_id) INCLUDE (matched_form_id, is_confirmed)` couvre déjà les `EXISTS`, rien à ajouter (`7e3fbf58`)

### Phase 2 — Frontend : filter-builder

- [x] Zone Filtres délimitée : ligne scope (structure étudiée + détection/validation) + pile de prédicats, boutons `+ Texte` / `+ Structure reconnue`, suppression par ligne (`ab6bd795`)
- [x] Prédicat Structure : multi-sélection en tags supprimables, opérateur explicite `reconnue comme l'une de` / `non reconnue comme aucune de` (`ab6bd795`)
- [x] Picker = toutes structures hors `site` (y compris l'étudiée) moins celles déjà posées (dédup global via `usedStructureIds`) (`ab6bd795`)
- [x] Params répétés `text`/`struct` dans l'URL + restauration au montage ; debounce conservé sur les champs texte ; application live (`ab6bd795`)

### Phase 3 — Tests

- [x] Intégration query : prédicats structure (recognized pending+confirmed, not_recognized, multi-OR), texte multi-ET, non-régression du scope (`7e3fbf58`)
- [x] Intégration API : params répétés `text`/`struct`, levée du garde-fou par prédicat structure (`7e3fbf58`)

## Questions ouvertes

— Aucune à ce stade (toutes tranchées au démarrage, cf. Décisions). À rouvrir au besoin pendant l'implémentation (ex. couverture d'index si perf insuffisante).
