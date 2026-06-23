# Chantier — Signatures institutionnelles (qualité et outillage)

Outiller la qualité des signatures institutionnelles — les adresses d'affiliation portées par les authorships et rattachées aux structures — à deux niveaux : d'une part enrichir la consultation des adresses (volumétrie par adresse, accès à la liste des publications, réduction des variantes de ponctuation) ; d'autre part mesurer la justesse des signatures par structure et par personne (typologie d'erreurs, taux calculé par publication). Chantier qui traîne de longue date et qui n'est pas trivial : la difficulté est moins technique que définitionnelle (qu'est-ce qu'une signature « correcte », à quel grain mesurer, sur quel périmètre de documents).

## Contexte

### Le modèle de données des adresses

Une signature institutionnelle est une chaîne d'adresse portée par une authorship. La table `addresses` stocke `raw_text` (la chaîne brute observée), `normalized_text` (une forme normalisée déjà calculée), `pub_count` (nombre de publications liées, déjà entretenu) et les pays. Le lien authorship ↔ adresse passe par `source_authorship_addresses`. Le rattachement d'une adresse à une structure passe par `address_structures`, qui porte `is_confirmed` (verdict du rattachement) et `matched_form_id` (la forme de nom de structure ayant déclenché le rattachement, vers `structure_name_forms`). La vue matérialisée `source_authorship_structures` résout authorship → structure en traversant `source_authorship_addresses` puis `address_structures`, restreinte aux rattachements confirmés et au périmètre d'affiliations courant.

### L'existant côté interface

Les pages `persons/[id]` et `laboratories/[id]` ont chacune un onglet « Adresses » qui liste les adresses rattachées à l'entité, avec pour chaque ligne le `raw_text` et un statut (Confirmée / En attente). Le `raw_text` est affiché tel quel : deux variantes ne différant que par la ponctuation apparaissent comme deux lignes distinctes, alors que `normalized_text` existe déjà en base et pourrait les regrouper. Le `pub_count` existe sur `addresses` mais n'est pas affiché dans ces onglets. Côté admin, `admin/addresses` permet de consulter et filtrer les adresses, y compris restreintes à une structure donnée ; `admin/structures` gère les structures et leurs formes de nom.

### L'incertitude sur la cible

L'avenir des onglets adresses des pages publiques est incertain : les statistiques par laboratoire ou par personne passeront vraisemblablement par les tableaux de bord. Une interface d'administration reste en revanche nécessaire pour consulter les listes d'adresses rattachées à une structure (existe déjà via `admin/addresses`) ou à une personne (à créer). Sur les pages publiques, la consultation détaillée des adresses est probablement superflue.

### Les deux axes issus du suivi

Le premier axe concerne l'outillage de consultation : afficher le nombre de publications par adresse, ouvrir l'accès à la liste de ces publications, et réduire le nombre de variantes affichées en s'appuyant sur la normalisation. Le second axe concerne la mesure de justesse : distinguer les adresses correctes des incorrectes pour exprimer un taux par laboratoire ou par personne, ce qui suppose de définir une typologie d'erreurs et leur caractère bloquant, de calculer le taux au grain de la publication et non de la signature, de restreindre le dénominateur aux publications au sens strict, et de trancher le sort des publications sans signature en base.

## Décisions

Ces décisions sont des orientations proposées, à confirmer ou amender ; seul le contexte ci-dessus est factuel.

1. **Deux axes traités séparément** : l'outillage de consultation et de normalisation des adresses d'un côté, la métrique de justesse des signatures de l'autre. Le premier est un préalable utile au second (on ne mesure bien que ce qu'on sait consulter) mais ne le bloque pas.

2. **Investir l'outillage admin plutôt que les pages publiques.** Vu l'incertitude sur la cible, privilégier la consultation côté administration (par structure : déjà là ; par personne : à ajouter) et laisser les taux de qualité rejoindre les tableaux de bord, plutôt que d'enrichir les onglets adresses des pages publiques.

3. **Réduire les variantes par la normalisation déjà disponible.** Regrouper l'affichage sur `normalized_text` plutôt que multiplier les `raw_text`, et n'envisager une normalisation plus poussée que si les variantes résiduelles le justifient.

4. **Mesurer au grain de la publication, pas de la signature.** Une même publication peut porter plusieurs signatures pour une même structure (plusieurs co-auteurs d'un même laboratoire) ou plusieurs adresses pour un même auteur ; le taux doit compter chaque publication une fois par structure ou par personne, sans pondérer par le nombre de co-auteurs.

5. **Restreindre le dénominateur aux publications au sens strict** via une liste blanche de `doc_type` (à définir), excluant les preprints, jeux de données et autres types pour lesquels la notion de signature institutionnelle correcte n'a pas de sens.

6. **Établir la typologie d'erreurs empiriquement**, à partir des cas réellement observés, en qualifiant chaque type par son caractère bloquant ou non, plutôt que de poser une typologie a priori.

## Phasage

### Phase 1 — Consultation des adresses

- [ ] Afficher le nombre de publications par adresse dans les vues de consultation.
- [ ] Ouvrir l'accès à la liste des publications rattachées à une adresse.
- [ ] Regrouper l'affichage des variantes sur `normalized_text`.
- [ ] Consultation des adresses rattachées à une personne côté admin (le pendant par structure existe).

### Phase 2 — Typologie des erreurs de signature

- [ ] Inventorier les cas d'erreur observés (adresse mal rattachée, signature attendue absente, etc.).
- [ ] Qualifier chaque type par son caractère bloquant ou non.

### Phase 3 — Métrique de justesse

- [ ] Calculer le taux au grain de la publication, par structure et par personne.
- [ ] Restreindre le dénominateur via la liste blanche de `doc_type`.
- [ ] Trancher le sort des publications sans signature en base (sources HAL / ScanR uniquement).

### Phase 4 — Restitution

- [ ] Exposer les taux par laboratoire et par personne dans les tableaux de bord.

## Questions ouvertes

- **Avenir des onglets adresses publics** : les conserver, ou basculer la consultation détaillée vers l'administration seule ?
- **Liste blanche des `doc_type`** au sens strict : quels types retenir au dénominateur ?
- **Publications sans signature en base** (sources HAL / ScanR seulement) : les exclure du dénominateur, ou les compter comme non couvertes ?
- **Définition d'« incorrecte »** : une adresse mal rattachée à une structure (faux positif), une signature attendue mais absente (faux négatif), ou les deux dans des indicateurs distincts ?
- **Niveau de normalisation** : se limiter à la ponctuation, ou viser un regroupement plus sémantique des variantes ?

## Liens

- Tables : `addresses`, `source_authorship_addresses`, `address_structures`, `structures`, `structure_name_forms` ; vue matérialisée `source_authorship_structures`.
- Onglets adresses : `interfaces/frontend/src/routes/persons/[id]/+page.svelte`, `interfaces/frontend/src/routes/laboratories/[id]/+page.svelte`.
- Administration : `interfaces/frontend/src/routes/admin/addresses/`, `interfaces/frontend/src/routes/admin/structures/`.
