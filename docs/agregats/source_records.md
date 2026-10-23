# Source_records — cycle de vie

*À jour le 2026-10-23.*

Un enregistrement source est l'image d'un document dans **une** source — HAL, OpenAlex, Web of Science, ScanR, theses.fr, Crossref, DataCite — avant toute fusion. C'est la couche qui garde ce que chaque source a dit, une ligne par couple source et identifiant dans cette source. Elle naît d'un import direct : la phase `normalize` transforme les données brutes déposées dans `staging` en enregistrements typés. Le pipeline seul y écrit ; l'API ne fait que les lire.

`domain/source_records/` définit les clés qui pilotent la résolution, les règles de correction de métadonnées, la correspondance entre les nomenclatures de type de document, et la conservation des valeurs d'origine.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `source_records` | Image d'un document dans une source | `(source, source_id)`, `publication_id`, `doi`, `doc_type`, `external_ids`, `raw_doc_type`, `title_normalized`, `corrections`, `source_extras` |
| `source_contributions` | Contribution source d'auteur pour cette source | `source_record_id`, `contributor_information_id`, `person_id`, `author_position`, `roles`, `in_perimeter`, `resolution_mode` |
| `contributor_information` | Informations du contributeur dédoublonnées | `author_name_normalized`, `identifiers`, `key_hash` |
| `source_contribution_addresses` | Lien entre une contribution source et ses adresses | `source_contribution_id`, `address_id` |
| `source_contribution_structures` | Vue matérialisée : contribution source ↔ structure du périmètre, avec l'indice | dérivée des adresses, des ROR, des structures HAL, des structures de thèse et du périmètre |

En amont se trouve `staging.raw_data`, qui conserve les données moissonnées et leur empreinte. En aval, `publications` reçoit le résultat de la fusion. Les contributions sources ont leur propre fiche, [source_contributions](source_contributions.md), et leur consolidation relève d'[contributions](contributions.md).

## Écriture par le pipeline

Une seule phase crée ces lignes, `normalize`, et une seule autre modifie leurs colonnes typées, `metadata_correction`.

**`normalize`.** Chaque ligne de `staging` non encore traitée devient un enregistrement, inséré ou mis à jour sur son couple source et identifiant. Les sources sont traitées de la plus fiable à la moins fiable, les suivantes complétant les champs vides sans écraser ce qui est déjà là. Aux colonnes communes — source et identifiant, titre, type de document, DOI, identifiants externes, revue, statut d'accès, langue — s'ajoutent des champs propres à chaque source : résumé, mots-clés, thématiques, données bibliographiques, adresses en ligne, collections HAL, embargo, nombre de citations, rétractation.

Lors d'un réimport, le rattachement à la publication est préservé, les identifiants externes sont réunis, le DOI est conservé et le type de document cède la place au plus récent. La normalisation des identifiants et le calcul du titre normalisé ont lieu à la lecture de la source, pas en SQL.

`normalize` écrit aussi les tables satellites : les contributions sources sont réécrites en bloc, les informations du contributeur dédoublonnées, les adresses créées au besoin et reliées aux contributions sources. La vue matérialisée reliant contributions sources et structures, elle, est produite par la phase `affiliations`.

**`metadata_correction`.** Trois sous-étapes, chacune dans sa transaction : rattachement à une revue par l'espace de noms du DOI, corrections portant sur un enregistrement isolé, puis corrections portant sur un groupe. Elles modifient les colonnes typées et conservent la valeur d'origine dans `corrections`, sous des clés qui ne se recouvrent pas. Chaque passage repart des données brutes reconstituées, si bien qu'il se rejoue sans dommage et rattrape une correction devenue caduque. Toute modification met l'enregistrement source dans la file de regroupement, `source_record_keys_queue`.

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

**Regroupement des doublons.** Chaque enregistrement marqué à reprendre est projeté en jetons de confirmation, les enregistrements partageant un jeton sont reliés, puis la phase décide ce qu'il faut en faire : rapprocher, créer, réunir ou séparer, puis repointer les rattachements.

**Autres lectures.** La phase `subjects` lit les thématiques source par source, en conservant leur provenance ; la phase `contributions` consolide les contributions sources ; la phase `persons` lit les contributions sources du périmètre.

## Lecture par l'API

Le détail d'une publication montre sa **provenance** : la liste de ses enregistrements source, les auteurs de l'import le plus récent pour chaque source, et les identifiants externes réunis. Aucune page ne présente ces enregistrements pour eux-mêmes — ils apparaissent comme la traçabilité d'une publication.

## Points d'attention

**Les clés de résolution sont décrites à deux endroits.** Le voisinage se calcule en SQL : `pipeline/transformation/publications/reconciliation/reconciliation.py` réunit par `UNION` un `SELECT` par famille de clé — DOI, clés scalaires d'`external_ids`, identifiant HAL, jeton de métadonnées.

Le `SELECT` des clés scalaires est engendré depuis l'énumération du domaine. Les trois autres sont écrits à la main, chaque famille demandant sa propre jointure : égalité sur une colonne pour le DOI, appartenance à un tableau pour l'identifiant HAL, égalité sur trois colonnes pour le jeton. Ajouter une clé de confirmation demande donc de toucher aussi ce fichier.
