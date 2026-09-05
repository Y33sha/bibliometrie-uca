# Domain — noyau métier pur

*À jour le 2026-09-05.*

Le noyau porte les règles métier indépendamment de leur implémentation : il n'ouvre aucune connexion, ignore la base et le protocole HTTP, et n'importe que la bibliothèque standard.

Les invariants de chaque agrégat, ses tables et son cycle de vie sont décrits dans les fiches de [docs/agregats/](../agregats/).

## Agrégats

Entités avec identité, comportement et invariants métier.

- **`SourcePublication`** (`domain/source_publications/`) est une publication telle que moissonnée depuis une source.
- **`Publication`** (`domain/publications/`) est l'entité unifiée que le pipeline dérive de plusieurs `SourcePublication` désignant le même document. Le dédoublonnage consiste à décider quels enregistrements désignent le même document.
- **`Person`** (`domain/persons/`) est l'entité unifiée que le pipeline dérive de plusieurs signatures désignant la même personne.
- **`IdentifierAttribution`** (`domain/persons/`) est l'attribution d'un identifiant à une personne : un même couple `(id_type, id_value)` ne peut être attribué qu'à une seule. La valeur elle-même est un value object ; c'est l'attribution qui porte un statut, et qu'on confirme, rejette ou transfère.
- **`Structure`** (`domain/structures/`) est un établissement ou unité de recherche. Les relations de tutelle entre structures forment un graphe acyclique.
- **`Perimeter`** (`domain/perimeters/`) est un ensemble de structures, défini par ses structures-racines et incluant tous leurs descendants.
- **`Journal`** (`domain/journals/`) est un support de publication — revue, recueil de proceedings, serveur de preprints — rattaché à un `Publisher`.
- **`Publisher`** (`domain/publishers/`) est un éditeur.

## Value objects

Immuables, identité par contenu.

- Identifiants de publication : `DOI`, `HALId`, `NNT`, `PMID`, `PMCID`, `ArxivId` (`domain/publications/identifiers.py`)
- Identifiants de personne : `ORCID`, `IdHAL`, `IdRef`, `HalPersonId` (`domain/persons/identifiers.py`)
- Identifiants de structure : `RorId`, `HalCollection` (`domain/structures/identifiers.py`)
- Formes de nom : `PersonNameForm`, `StructureNameForm`

## Utilitaires partagés

- `entity_resolution.py` — regroupement en composantes connexes, primitive du dédoublonnage
- `sources/` — référentiel des 7 sources et des règles qui leur sont propres
- `normalize.py`, `dates.py` — normalisation des textes et des dates
- `countries.py` — règles sur les pays des publications
- `stats.py` — vocabulaire du pivot : ce qu'on peut grouper, ventiler et mesurer sur le corpus, indépendamment de toute requête
- `urls.py` — reconnaître le service qu'une URL désigne pour interpréter ce qu'elle porte : une adresse sur `doi.org` est un DOI, un `schemeUri` sur `orcid.org` annonce un ORCID
- `config.py` — quels réglages d'exploitation une page publique peut lire
- `errors.py` — exceptions métier
- `types.py` — le type d'une donnée JSON, et des accesseurs qui en rendent la forme attendue ou rien, pour qu'un champ mal formé n'interrompe pas un moissonnage

## Hydratation des agrégats

L'hydratation sert là où le traitement porte sur une entité à la fois : les corrections manuelles, qui chargent, modifient et enregistrent l'entité éditée, et `refresh_from_sources`, qui recalcule les métadonnées canoniques d'une publication depuis ses sources.

Les traitements effectués en masse par le pipeline — résolution des affiliations, dédoublonnage des publications et des personnes… — opèrent en SQL sur tout le corpus.

- Chaque repository d'agrégat expose `find_by_id(id) -> Entity | None` qui charge l'*aggregate root*. Pour les agrégats riches (`Publication`, `Person`, `Structure`), les value objects internes — formes de nom, identifiants — sont chargés avec lui.
- Les références entre agrégats sont **par id**, pas par objet : `Journal.publisher_id`, `Perimeter.root_structure_ids` — pas d'hydratation transitive.
