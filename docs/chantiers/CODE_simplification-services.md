# Chantier — Simplification des services applicatifs

## Contexte

Une écriture de l'API est une fonction de `application/services/`, sans commit : la requête commite à son terme, avec ses événements d'audit (`db_conn`). Une relecture du dossier relève les sources de complexité suivantes.

- Les ports de recalcul du pipeline (`PerimeterStructures`, `SerialRecompute`, `PublicationPerimeterRecompute`, `PublicationCountRecompute`, `CountryRecompute`) sont des instances uniques, qui reçoivent `conn` à chaque appel. Les services prennent donc `conn` pour le seul transmettre. Les repositories, eux, sont construits sur la connexion de la requête.
- Chaque route d'écriture déclare de 3 à 6 dépendances pour fournir au service ses repositories et ses ports.
- `structures._to_row` compose la ligne de réponse de l'API : `structure_type` sous le nom `type`, identifiants en chaînes.
- `create_structure` reçoit 8 paramètres séparés, `create_name_form` 5. Leurs mises à jour reçoivent le modèle typé (`StructureUpdate`, `NameFormUpdate`). Un champ ajouté touche le modèle, le routeur, le service et le domaine.
- `load_merge_pair` charge les deux agrégats d'une fusion pour en vérifier l'existence. Ses trois appelants ignorent le couple chargé. Pour une personne, l'agrégat contient ses identifiants et ses formes de nom.
- Détails :
  - `persons.py` définit un `logger` qu'il n'utilise pas ;
  - `update_identifier_status` et `update_name_form_status` typent le statut en `str`, et le comparent l'un à `AttributionStatus.REJECTED.value`, l'autre à `"rejected"`. Le routeur transmet un `AttributionStatus` ;
  - `create_tutelle` recalcule la clôture des périmètres quand la tutelle existait déjà ;
  - `set_country` rend `[address_id]` ;
  - les deux propagations qui suivent une écriture d'adresse vivent dans deux paquets : celle des pays dans `addresses/countries.py`, celle d'`in_perimeter` dans `contributions/core.py`.
- Docstrings : plaidoyers (module `publishers`, `_merge`), renvoi au module voisin (module `serials`), description périmée de l'aperçu dans `requalify_publications_for_serial`, retours à la ligne non sémantiques dans `_resolve_rejection`.

## Décisions

- Les ports de recalcul sont construits sur la connexion de la requête par les fabriques de `interfaces/api/deps.py`, comme les repositories. Leurs méthodes perdent le paramètre `conn`.
- Le service rend l'agrégat ; le routeur compose la réponse.
- Les créations de structure et de forme de nom reçoivent un modèle typé, déclaré dans le port comme `StructureUpdate`.
- Les mises à jour des éditeurs et des périmètres gardent leur forme : un `edit` de l'agrégat, sur le modèle de `Serial.edit`, coûterait plus qu'il ne simplifie.
- La vérification d'existence des fusions rend `None`.

## Phasage

### Phase 1 — Ports de recalcul liés à la connexion

- [ ] Ports de `application/ports/pipeline/` sans paramètre `conn`
- [ ] Adaptateurs exposés par `pipeline/public.py` construits sur une connexion. Seuls l'API et les scripts les instancient ; le pipeline appelle les fonctions qu'ils enveloppent
- [ ] Fabriques de `deps.py` sur `DbConn` ; tâches de fond sur leur propre connexion
- [ ] `conn` retiré des services et des routes, sauf l'aperçu du changement de type de revue (savepoint)

### Phase 2 — Retouches sans décision de fond

- [ ] `load_merge_pair` en vérification d'existence, sans retour
- [ ] Statuts typés `AttributionStatus` dans `persons.py` ; `logger` inutilisé retiré
- [ ] `create_tutelle` : recalcul de la clôture seulement pour une tutelle créée
- [ ] `set_country` sans liste artificielle en retour
- [ ] Propagations consécutives à une écriture d'adresse réunies

### Phase 3 — Frontière entre service et interface

- [ ] `_to_row` remplacé par la composition de `StructureOut` dans le routeur
- [ ] `StructureCreate` et `NameFormCreate` dans le port, reçus par `create_structure` et `create_name_form`

### Phase 4 — Docstrings

- [ ] Relecture de style de `application/services/`

## Questions ouvertes

- Un objet de service par agrégat, construit dans `deps.py`, réduirait chaque route d'écriture à une dépendance. Le volume de câblage restant après la phase 1 décide de son intérêt.
