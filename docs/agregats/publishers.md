# Éditeurs — cycle de vie

*À jour le 2026-10-25.*

Un éditeur publie les publications et reçoit les frais de publication. L'éditeur d'une publication est celui de la date de publication ; l'éditeur d'une publication en série se déduit de ses publications. Une plateforme qui héberge des publications sans les publier n'est pas un éditeur (fiche [plateformes](platforms.md)). Il se reconnaît par son identifiant OpenAlex quand une source en fournit un, sinon par son nom, via les formes enregistrées dans `publisher_name_forms`. `domain/publishers/publisher.py` définit sa structure — nom, pays, identifiant OpenAlex, type ; la résolution, la fusion et l'enrichissement vivent dans les services et leurs adaptateurs SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `publishers` | L'éditeur | `name` / `name_normalized`, `country`, `openalex_id` (unique), `publisher_type`, `publication_count` |
| `publisher_name_forms` | Formes de nom permettant de reconnaître un éditeur | `publisher_id`, `form_normalized` |
| `doi_prefixes` | Correspondance entre un préfixe de DOI et un éditeur | `publisher_id`, `crossref_member_id`, `datacite_client_symbol`, `crossref_checked_at`, `datacite_checked_at` |

Une forme de nom d'éditeur est unique dans toute la table, là où une forme de titre de revue n'est unique que pour un éditeur donné : deux éditeurs ne peuvent pas revendiquer la même forme de nom.

Les tables `serials`, `monographs`, `source_records`, `publications`, `serial_name_forms` et `apc_payments` référencent un éditeur par leur colonne `publisher_id`.

## Écriture par le pipeline

**Rattachement (`normalize`).** Chaque normaliseur appelle `find_or_create_publisher` (`pipeline/transformation/publishing/find_or_create.py`), qui essaie d'abord l'identifiant OpenAlex, puis se rabat sur la forme de nom — reconnue ou créée — avant de transmettre l'éditeur à la recherche de la revue par son titre. Seul OpenAlex fournit un identifiant d'éditeur : l'organisation hôte de la source de sa localisation principale, revue ou plateforme d'ebooks. L'enregistrement source reçoit cet éditeur, sauf une production hébergée sans être publiée : preprint, jeu de données, rapport, thèse, ou document DataCite sans revue ni monographie, dont l'« éditeur » est l'entrepôt.

**Éditeur des publications (`publications`).** Le recalcul d'une publication lui donne l'éditeur de la date de publication : le titulaire du préfixe de son DOI Crossref, à défaut l'éditeur de ses enregistrements sources. Une plateforme d'éditeurs qui enregistre les DOI des revues qu'elle diffuse en est exclue (fiche [publications](../donnees/03-publications.md)).

**Résolution par préfixe de DOI (`publishing`).** Une sous-étape par agence d'enregistrement, Crossref puis DataCite, interroge l'API de l'agence sur les préfixes qu'elle n'a pas vus. Elle enregistre les métadonnées obtenues, reconnaît ou crée l'éditeur par sa forme de nom, comme dans `normalize`, et renseigne `doi_prefixes.publisher_id`. `crossref_checked_at` et `datacite_checked_at` retiennent que l'agence a répondu, préfixe connu ou non. Un préfixe dont l'API est indisponible est repris au run suivant.

**Éditeur des publications en série (`finalize`).** Chaque publication en série prend l'éditeur de ses publications les plus récentes (fiche [publications en série](serials.md)).

**Autres noms (`publishing`).** Un éditeur que nomment les sources rejoint le titulaire Crossref des préfixes de ses enregistrements sources quand leurs noms sont compatibles (`domain/publishers/aliases.py`, [publishing](../pipeline/05-publishing.md)). Une marque ou un éditeur racheté reste distinct.

**Enrichissement du pays, hors pipeline.** `interfaces/cli/maintenance/enrich_publishers.py` renseigne le pays depuis OpenAlex, et seulement là où il est absent : une valeur saisie à la main est conservée.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/publishers.py`, adaptateur `PgPublisherRepository`.

**Éditer un éditeur** (`PUT /api/publishers/{id}`). Seuls les champs transmis sont modifiés ; le repository re-dérive `name_normalized` depuis le nom.

**Fusionner deux éditeurs** (`POST /api/publishers/{id}/merge`). Les revues que les deux se partagent sous un même titre sont fusionnées d'abord, puis `merge_publisher_into` repointe vers l'éditeur conservé chaque table qui référence l'éditeur absorbé, avant de recaler les compteurs.

L'opération est refusée quand deux revues de même titre, une chez chaque éditeur, ont des ISSN différents : leurs identités sont distinctes. Elle l'est aussi quand un même titre apparaît deux fois chez l'un des deux éditeurs.

## Lecture par le pipeline

`publishers.publication_count` compte les publications du périmètre qui ont l'éditeur (`publications.publisher_id`). La phase `finalize` fait ce calcul en totalité une fois le périmètre posé ; une fusion administrative ne recalcule que les éditeurs concernés.

## Lecture par l'API

Lecture `infrastructure/read_models/publishers/`, classe `PublisherQueries`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| Liste et facettes | Éditeurs filtrables, avec leur nombre de publications en série, leur nombre de publications et leurs préfixes de DOI ; facettes par type et par pays |
| Détail et tableau de bord | Types des publications en série de l'éditeur, types de document et statuts d'accès de ses publications du périmètre, sujets |
