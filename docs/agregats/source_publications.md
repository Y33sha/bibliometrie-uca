# Source_publications — cycle de vie

*À jour le 2026-09-06.*

Un enregistrement source est l'image d'un document dans **une** source — HAL, OpenAlex, Web of Science, ScanR, theses.fr, Crossref, DataCite — avant toute fusion. C'est la couche qui garde ce que chaque source a dit, une ligne par couple source et identifiant dans cette source. Elle naît d'un import direct : la phase `normalize` transforme les données brutes déposées dans `staging` en enregistrements typés. Le pipeline seul y écrit ; l'API ne fait que les lire.

`domain/source_publications/` porte les clés qui pilotent la résolution, les règles de correction de métadonnées, la correspondance entre les nomenclatures de type de document, et la conservation des valeurs d'origine.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `source_publications` | Image d'un document dans une source | `(source, source_id)`, `publication_id`, `doi`, `doc_type`, `external_ids`, `title_normalized`, `raw_metadata`, `meta`, `keys_dirty` |
| `source_authorships` | Signature d'auteur pour cette source | `source_publication_id`, `identity_id`, `person_id`, `authorship_id`, `author_position`, `roles`, `in_perimeter`, `resolution_mode` |
| `author_identifying_keys` | Identité d'auteur dédoublonnée | `author_name_normalized`, `person_identifiers`, `key_hash` |
| `source_authorship_addresses` | Lien entre une signature et ses adresses | `source_authorship_id`, `address_id` |
| `source_authorship_structures` | Vue matérialisée : signature ↔ structure du périmètre | dérivée des adresses, de leurs rattachements et du périmètre |

En amont se trouve `staging.raw_data`, qui conserve les données moissonnées et leur empreinte. En aval, `publications` reçoit le résultat de la fusion. Les signatures ont leur propre fiche, [source_authorships](source_authorships.md), et leur consolidation relève d'[authorships](authorships.md).

## Écriture par le pipeline

Une seule phase crée ces lignes, `normalize`, et une seule autre modifie leurs colonnes typées, `metadata_correction`.

**`normalize`.** Chaque ligne de `staging` non encore traitée devient un enregistrement, inséré ou mis à jour sur son couple source et identifiant. Les sources sont traitées de la plus fiable à la moins fiable, les suivantes complétant les champs vides sans écraser ce qui est déjà là. Aux colonnes communes — identité, titre, type de document, DOI, identifiants externes, revue, statut d'accès, langue — s'ajoutent des champs propres à chaque source : résumé, mots-clés, thématiques, données bibliographiques, adresses en ligne, collections HAL, embargo, nombre de citations, rétractation.

Lors d'un réimport, le rattachement à la publication est préservé, les identifiants externes sont réunis, le DOI est conservé et le type de document cède la place au plus récent. La normalisation des identifiants et le calcul du titre normalisé ont lieu à la lecture de la source, pas en SQL.

`normalize` écrit aussi les tables satellites : les signatures sont réécrites en bloc, les identités d'auteur dédoublonnées, les adresses créées au besoin et reliées aux signatures. La vue matérialisée reliant signatures et structures, elle, est produite par la phase `affiliations`.

**`metadata_correction`.** Trois sous-étapes, chacune dans sa transaction : rattachement à une revue par préfixe de DOI, corrections portant sur un enregistrement isolé, puis corrections portant sur un groupe. Elles modifient les colonnes typées et conservent la valeur d'origine dans `raw_metadata`, sous des clés qui ne se recouvrent pas. Chaque passage repart des données brutes reconstituées, si bien qu'il se rejoue sans dommage et rattrape une correction devenue caduque. Toute modification pose `keys_dirty`, ce qui remet l'enregistrement dans la file de regroupement.

**`fetch_missing` et `fetch_stale`** s'exécutent avant `normalize` et n'écrivent pas cette couche : elles alimentent `staging`, que `normalize` consomme dans le même passage. La reprise sans doublon tient à l'empreinte des données brutes, portée par `staging` : une empreinte inchangée laisse la ligne traitée, une empreinte différente la remet en file et `normalize` met à jour le **même** enregistrement.

## Écriture par l'API

**Aucune.** Ces enregistrements sont la trace de ce que les sources ont fourni : rien ne les édite à la main. Une métadonnée fausse se corrige par une règle de `metadata_correction`, et l'édition manuelle porte sur la publication consolidée ou sur les revues.

## Lecture par le pipeline

**Consolidation en publication.** `refresh_from_sources` lit tous les enregistrements d'une publication et recalcule son état en entier. Champ par champ :

- la première valeur non nulle, selon le classement des sources ;
- pour le type de document, un sous-type d'article précis venu d'une source moins fiable l'emporte sur le type générique de Crossref ;
- pour l'accès, le statut le plus ouvert ;
- pour les listes, leur réunion dédoublonnée.

Les valeurs lues sont déjà corrigées.

**Regroupement des doublons.** Chaque enregistrement marqué à reprendre est projeté en jetons de confirmation, les enregistrements partageant un jeton sont reliés, et la décision porte ensuite sur ce qu'il faut en faire : rapprocher, créer, réunir ou séparer, puis repointer les rattachements.

**Autres lectures.** La phase `subjects` lit les thématiques source par source, en conservant leur provenance ; la phase `authorships` consolide les signatures ; la phase `persons` lit les signatures du périmètre.

## Lecture par l'API

Le détail d'une publication montre sa **provenance** : la liste de ses enregistrements source, les auteurs de l'import le plus récent pour chaque source, et les identifiants externes réunis. Aucune page ne présente ces enregistrements pour eux-mêmes — ils apparaissent comme la traçabilité d'une publication.

## Points d'attention

**Les clés de résolution sont décrites à deux endroits.** Le voisinage se calcule en SQL : `infrastructure/pipeline/publications/reconciliation.py` réunit par `UNION` un `SELECT` par famille de clé — DOI, clés scalaires d'`external_ids`, identifiant HAL, jeton de métadonnées.

Le `SELECT` des clés scalaires est engendré depuis l'énumération du domaine. Les trois autres sont écrits à la main, chaque famille demandant sa propre jointure : égalité sur une colonne pour le DOI, appartenance à un tableau pour l'identifiant HAL, égalité sur trois colonnes pour le jeton. Ajouter une clé de confirmation demande donc de toucher aussi ce fichier.
