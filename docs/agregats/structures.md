# Structures — cycle de vie

*À jour le 2026-09-04.*

Une structure est une unité de l'établissement ou un partenaire : composante, laboratoire, tutelle, site. C'est un **référentiel saisi à la main** — les structures sont créées et modifiées à la main, jamais par le pipeline, qui se contente de les lire pour reconnaître des adresses et pour composer les périmètres.

`domain/structures/` valide le type, l'identifiant ROR et la collection HAL, et porte les règles du graphe de rattachement.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `structures` | La structure | `code` (unique), `name`, `acronym`, `structure_type`, `ror_id`, `rnsr_id`, `hal_collection`, `api_ids` |
| `structure_relations` | Rattachement d'une structure à une autre | `parent_id`, `child_id`, `relation_type` (`est_tutelle_de` ou `est_partenaire_de`), unicité du triplet, une structure ne pouvant se rattacher à elle-même |
| `structure_name_forms` | Formes de nom servant à reconnaître une structure dans une adresse | `structure_id`, `form_text` normalisé, `is_word_boundary`, `is_excluding`, `requires_context_of` |

Les périmètres, dont les racines sont des structures, ont leur propre fiche : [perimeters](perimeters.md).

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/structures.py`, commandes dans `application/services/structures/commands.py`, adaptateur `PgStructureRepository`. C'est le seul chemin d'écriture.

**Structures** (`POST`, `PUT`, `DELETE /api/structures/{id}`). Le domaine valide le type, l'identifiant ROR et la collection HAL ; le repository valide `api_ids` contre son modèle. La suppression entraîne en base celle des lignes qui rattachent la structure aux signatures et aux authorships.

**Rattachements** (`POST /api/structures/relations`, `DELETE`). La création charge d'abord les ancêtres du parent, puis le domaine refuse l'auto-rattachement et tout rattachement qui refermerait un cycle. Créer un rattachement qui existe déjà ne produit rien.

**Formes de nom** (`POST`, `PUT`, `DELETE /api/name-forms`). Le texte est normalisé avant enregistrement, et la contrainte de frontière de mot est imposée d'office aux formes courtes.

Créer ou modifier un rattachement, comme supprimer une structure, recalcule les périmètres ; une suppression retire en outre la structure des racines de tous les périmètres. Modifier les seuls attributs d'une structure ne les touche pas. Chaque opération est consignée dans le journal d'audit.

## Écriture par le pipeline

**Aucune.** Le pipeline ne crée ni ne modifie de structure.

## Lecture par le pipeline

**Reconnaissance des adresses** (phase `affiliations`). `infrastructure/pipeline/affiliations/address_resolution.py` charge les formes de nom dans un automate Aho-Corasick qui balaie le texte normalisé des adresses. Trois options règlent la reconnaissance : `is_word_boundary` exige que la forme soit délimitée par des frontières de mot ; `is_excluding` fait de la forme un motif de rejet ; `requires_context_of` subordonne la reconnaissance à la présence, dans la même adresse, des structures citées.

**Composition des périmètres.** Les rattachements de type `est_tutelle_de` fournissent la descente récursive qui remplit `perimeter_structures` à partir des racines déclarées. C'est par là que les structures décident, au bout de la chaîne, de l'appartenance d'une signature au périmètre.

## Lecture par l'API

**Administration.** Port `application/ports/read_models/structures_queries.py`, adaptateur `PgStructuresQueries` : liste filtrable par type, avec une recherche sur le nom, l'acronyme et le code qui ignore les accents ; détail d'une structure avec ses parents, ses enfants et ses formes de nom.

**Page des laboratoires.** Lecture des structures de type laboratoire appartenant au périmètre, avec leurs tutelles. Les types affichés sont réglables par configuration.

## Invariants métier

**Identité.** Le `code` est unique.

**Le graphe reste sans cycle.** Une structure ne peut se rattacher à elle-même, ni à l'un de ses descendants. La contrainte est portée à la fois par la base et par le domaine, qui vérifie les ancêtres avant d'accepter.

**Une forme courte exige une frontière de mot.** Une forme de six caractères normalisés ou moins ne peut être enregistrée sans `is_word_boundary`, faute de quoi elle serait reconnue à l'intérieur d'autres mots — « uca » dans « éducation ». La règle est imposée par une contrainte de base et par le service.

**Identifiants normalisés.** L'identifiant ROR et la collection HAL sont validés et normalisés à l'écriture comme à la lecture ; `api_ids` est validé contre son modèle.

**Formes de nom normalisées.** Le texte d'une forme passe par la même normalisation que les adresses auxquelles il sera confronté.
