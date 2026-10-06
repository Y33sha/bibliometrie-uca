# Chantier — Nom et prénom scindés dès la normalisation

## Contexte

Une signature porte un seul nom brut : `source_authorships.raw_author_name`. Le matching des personnes le découpe en nom et prénom avec `parse_raw_author_name` (`domain/persons/name_matching.py`). Sans virgule, le parseur prend le dernier mot pour nom de famille, sauf particule. « Dupont Marie » donne donc nom « Marie », prénom « Dupont ».

Cinq sources sur sept fournissent nom et prénom séparés. La normalisation les réunit en une chaîne, que le matching découpe ensuite.

| Source | Champs fournis |
|---|---|
| Crossref | `given`, `family` |
| DataCite | `givenName`, `familyName` |
| WoS | `first_name`, `last_name` |
| HAL | `forename`, `surname` (TEI) |
| theses.fr | `prenom`, `nom` |
| OpenAlex | `raw_author_name` (chaîne unique) |
| ScanR | `fullName` (chaîne unique) |

OpenAlex et ScanR portent environ la moitié des signatures du périmètre. Une même personne a le plus souvent aussi une signature d'une source qui fournit le découpage.

Un test de record linkage probabiliste (Splink) sur les signatures du périmètre bute sur ces inversions. Des signatures de même ORCID ont nom et prénom inversés, donc le modèle sous-pondère la discordance des prénoms. Le test reprend sur les noms découpés.

## Décisions

- Le découpage nom / prénom précède tout matching.
- Le matching des personnes s'appuie sur le nom et le prénom découpés.
- `source_authorships` stocke ce que la source fournit : `raw_last_name` et `raw_first_name` quand la source les sépare, sinon `raw_author_name`. Une contrainte impose l'une ou l'autre forme.
- `author_identifying_keys` porte le découpage retenu, normalisé, dans la clé d'identité.
- `person_name_forms` stocke une chaîne « prénom nom » normalisée, au format de `author_identifying_keys.author_name_normalized`.
- L'interface présente les formes de nom (volet personne, formes confirmées et rejetées) telles que les sources les donnent, au format « Prénom Nom ».

## Phasage

### Phase 1 — Fiabilité du découpage

Mesure sur les signatures du périmètre rattachées à une personne du référentiel RH, par comparaison avec le nom et le prénom de la personne.

- [x] Champs natifs : 96 à 98 % conformes pour Crossref, HAL, WoS et theses.fr. Inversions : 0,3 à 0,5 %, 0,03 % pour theses.fr. Ce sont des erreurs de saisie de la source (nom dans le champ prénom).
- [x] DataCite : environ 10 % des créateurs portent le nom complet dans `familyName`, avec `givenName` vide. Ces signatures relèvent du parseur.
- [x] WoS : environ 1 % des noms de famille composés sont répartis entre `last_name` et `first_name`.
- [x] Parseur sur OpenAlex et ScanR : 96 % conformes, 0,7 % d'inversions, 1 à 1,6 % de découpages partiels (noms de famille composés).

### Phase 2 — Schéma et normalisation

La synchronisation des signatures d'une notice renormalisée rapproche les signatures par identité. Un oneshot remplit donc les nouvelles colonnes en place avant toute renormalisation, pour que les signatures gardent leur identifiant, leur personne et leur épinglage.

- [x] Objet valeur du nom fourni par la source (`SignatureName`) : nom et prénom, ou chaîne brute ; découpage retenu et forme « Prénom Nom ».
- [x] Prénom réduit à des initiales normalisé en initiales séparées : « JP » et « J.-P. » donnent « j p ».
- [x] Migration : `raw_last_name` et `raw_first_name` sur `source_authorships` ; nom et prénom normalisés dans la clé d'identité de `author_identifying_keys`.
- [x] Normaliseurs Crossref, DataCite, WoS et theses.fr : champs natifs. DataCite sans `givenName` : chaîne brute.
- [x] Normaliseur HAL : `forename` et `surname` du TEI, équivalents au nom Solr sur tout le raw store.
- [x] Normaliseurs OpenAlex et ScanR : chaîne brute, découpée par le parseur.
- [x] Oneshot : nouvelles colonnes des signatures existantes, relues dans le raw store, et rattachement à leur nouvelle identité. Appliqué puis supprimé.
- [x] Migration : clé d'identité réduite au nom, au prénom et aux identifiants ; `author_name_normalized` calculé.
- [x] Matching et affichage : lecture du nom et du prénom découpés.

### Phase 3 — Matching des personnes et correction des inversions

Une inversion se repère en confrontant le découpage d'une signature aux personnes connues : la correction des inversions et le matching par forme de nom vont ensemble.

- [x] Nom de famille réduit à des initiales : le découpage retenu les place en prénom. Trois cas, environ 13 000 signatures : format « Nom I. » découpé par le parseur (« Del Buono L. »), format « I., Nom » (« C., Küll »), champs natifs inversés (surname « M. », forename « Brigante »). Signatures existantes rattachées à leur identité corrigée.
- [x] Formes de nom dans l'ordre « prénom nom ». Formes d'une personne : « prénom nom » et « initiales nom ». Verdicts réécrits dans cet ordre d'après leur découpage.
- [x] Matching par forme de nom et corroboration d'un identifiant : forme « prénom nom », puis « nom prénom ».
- [ ] Personnes au nom de famille fait d'initiales (17) : supprimées par un oneshot, puis recréées ou rattachées par le pipeline d'après le découpage de leurs signatures.
- [ ] Effet mesuré sur les rattachements, les signatures orphelines et les personnes créées.

### Phase 4 — Interface

- [ ] Volet personne et listes de formes de nom confirmées et rejetées : formes « Prénom Nom » des sources.

### Phase 5 — Reprise du test Splink

- [ ] Modèle relancé sur les noms découpés, comparé aux rattachements de la base.

### Phase 6 — Documentation

- [ ] Mise à jour de `docs/pipeline` (normalisation, personnes).

## Questions ouvertes

- Affichage d'une forme normalisée qui regroupe plusieurs graphies brutes : la plus fréquente, ou toutes ?
- Parseur : la règle des initiales finales vise le format « Nom I. » (« Del Buono L. »). Elle découpe aussi « Prénom Nom I. » en nom « Prénom Nom » : « Jean PERRIOT M.D. », « Valérie Julian V ». Fréquence à mesurer.
