# Normalisation

*À jour le 2026-10-26.*

La phase `normalize` transforme les données moissonnées (`staging`) en [enregistrements sources](../donnees/02-sources.md) et en contributions sources. Elle écrit aussi les localisations, les adresses, et crée ou reconnaît les monographies, les éditeurs et les plateformes. L'enregistrement source décrit sa série (`biblio.journal`) ; la phase [`publishing`](05-publishing.md) le rattache à sa publication en série.

L'enregistrement source reçoit l'éditeur que nomme sa source, sauf pour un document hébergé sans être publié (preprint, jeu de données, rapport, thèse). Les localisations et leurs plateformes sont décrites avec l'[édition](../donnees/07-publishing.md#plateformes).

Chaque normaliseur reporte dans `source_contributions` les données de chaque contribution source : identifiants de l'auteur (ORCID, IdRef…) et affiliations. Chaque identifiant prend sa forme canonique ; une valeur mal formée est écartée et journalisée.

Une contribution source collective (collaboration, consortium, groupe d'étude…) reste à sa position, marquée `collective`. La marque vient de la source quand elle distingue les collectifs : entrée Crossref à `name` seul, créateur DataCite `Organizational`. Sinon, une règle sur le nom décide (`domain/persons/collective_names.py`).

Le type de document et la langue de la source sont traduits dans le vocabulaire du référentiel : `doc_type` par la table de correspondance de la source, `language` par les formes de `language_forms`. `raw_doc_type` et `raw_language` gardent la valeur de la source.

Chaque normaliseur pose aussi la licence de l'enregistrement source (`source_records.license`), ramenée au vocabulaire fermé de `domain/publications/licenses.py`. La forme brute reste dans `source_extras`.

En fin de phase, les `source_records` d'un document marqué `disappeared_at` par [`fetch_stale`](02-harvest.md#documents-périmés-et-disparus-fetch_stale) sont supprimées ; leurs `source_contributions` sont supprimées en cascade. La ligne de `staging` reste, avec sa marque.

En fin de phase, le `raw_data` de `staging` est vidé.

## Synchronisation des contributions sources

Chaque contribution source entrante retrouve en base la contribution source de mêmes informations du contributeur (nom, prénom et identifiants normalisés, marque collective), puis de même position si ces informations sont répétées. Une contribution source retrouvée garde son identifiant, donc son épinglage. Les autres sont insérées ou supprimées.

Un enregistrement source garde ses contributions sources en l'état si la partie auteurs de son payload est inchangée depuis la dernière normalisation. L'option `--normalize-full` vide l'empreinte de cette partie pour tous les enregistrements sources des sources normalisées : leurs contributions sources se resynchronisent à leur prochaine normalisation.

## Archivage du payload brut

Avant de vider `raw_data`, la normalisation dépose le payload hors base, dans le raw store (`infrastructure/raw_store/`) : un fichier `data/raw_store/{source}/{source_id}.json.gz` par document. L'option [`--raw-store`](../exploitation/03-pipeline.md#divers) déclenche cet archivage : sans elle, le payload est perdu à la vidange.

Le script `interfaces/cli/maintenance/rehydrate_staging_from_raw_store.py` réinjecte les payloads d'une source, pour rejouer sa normalisation.
