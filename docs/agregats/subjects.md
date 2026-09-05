# Sujets — cycle de vie

*À jour le 2026-09-04.*

Un sujet est un concept thématique attaché à une publication par une source : domaine HAL, discipline de thèse, vedette-matière RAMEAU, concept OpenAlex. Le pipeline en est la seule autorité d'écriture ; l'API ne fait que les lire.

Aucun objet de domaine ne lui correspond : un sujet vit comme libellé et lignes SQL. La seule règle venue de `domain/` est `normalize_label`, qui réduit les espaces sans toucher à la casse ni aux accents.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `subjects` | Le sujet | `label`, unique sur sa forme minuscule, `language`, `usage_count`, `created_at` |
| `publication_subjects` | Lien entre une publication et un sujet, pour une source donnée | clé `(publication_id, subject_id, source)`, `rejected`, `created_at` |
| `subject_cooccurrences` | Vue matérialisée : paires de sujets présents sur une même publication | les deux sujets ordonnés, le nombre de publications concernées, à partir de deux |

Deux libellés qui ne diffèrent que par la casse convergent vers un seul sujet, et c'est la première forme rencontrée qui est conservée. Un même sujet attribué par deux sources donne en revanche **deux** liens, la source faisant partie de la clé.

## Écriture par le pipeline

Une seule phase écrit ces tables, `subjects`, exécutée après `authorships`. Elle comporte deux étapes inséparables, chacune dans sa transaction.

**Ingestion.** Sont retenues les publications jamais traitées, et celles modifiées depuis le dernier enregistrement de leurs sujets. La sélection compare ces deux dates, sans colonne de marquage comme en portent d'autres phases. Leurs liens **non rejetés** sont effacés, puis reconstruits enregistrement source par enregistrement source : l'extracteur propre à chaque source réduit ses thématiques à une liste de libellés, un cache mutualise l'écriture d'un même libellé — y compris entre sources —, et les liens sont insérés en une fois avec leur source. Les sujets restés sans aucun lien sont supprimés en fin d'étape. `--rebuild-subjects` reprend l'intégralité du stock.

**Extracteurs.** HAL fournit ses domaines, OpenAlex ses quatre niveaux de concepts mis à plat, le Web of Science ses catégories et ses vedettes, ScanR ses domaines, theses.fr la discipline et les vedettes RAMEAU.

**Co-occurrences.** `usage_count` est recalculé — le nombre de publications distinctes par sujet, rejets exclus — puis la vue des paires est rafraîchie. Le calcul ne dépend que de l'état courant des liens, et se rejoue donc sans dommage.

## Écriture par l'API

**Aucune.** Ni création ni édition de sujet.

## Lecture par le pipeline

L'ingestion lit les thématiques dans les enregistrements source, et non dans le détail consolidé de la publication : c'est ce qui permet de retenir quelle source a fourni chaque lien. Les co-occurrences lisent les liens non rejetés.

Aucun filtre de périmètre n'est appliqué, et il n'en faut pas : la phase `authorships` a déjà supprimé en amont les publications hors périmètre, si bien que les liens ne portent que sur le périmètre et que les deux valeurs dérivées en héritent.

## Lecture par l'API

Port `application/ports/read_models/subjects_queries.py`, adaptateur `PgSubjectsQueries`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/subjects` | Liste paginée, triée par usage décroissant, avec recherche insensible aux accents et seuil d'usage minimal |
| `GET /api/subjects/{id}` | Le sujet et ses voisins les plus fréquents, d'après la vue des co-occurrences |

Les sujets alimentent aussi les palmarès affichés ailleurs — tableaux de bord d'éditeur et de laboratoire, détail d'une publication — par des lectures propres à ces pages.

## Points d'attention

**Seuls les concepts d'ontologie deviennent des sujets.** Les mots-clés libres que fournissent les sources — c'est tout ce que Crossref propose — restent sur l'enregistrement source et s'affichent avec le détail de la publication, sans entrer dans ces tables. La distinction est délibérée : un vocabulaire contrôlé se compte et se recoupe, un mot-clé libre non.

**La colonne `rejected` est respectée partout mais aucune interface ne la pose.** Elle exclut le lien du comptage d'usage et des co-occurrences, survit à l'effacement de l'ingestion, et empêche la suppression du sujet. Aucun point d'entrée ne permet aujourd'hui de la renseigner.

## Invariants métier

**Identité d'un sujet.** L'unicité porte sur le libellé en minuscules. Le libellé conservé est celui de la première insertion, et la langue celle de la première source qui en déclare une : les suivantes ne l'écrasent pas.

**Attribution par source.** Chaque lien retient la source qui l'a fourni ; un même sujet venu de deux sources donne deux liens. L'ingestion efface et reconstruit les liens non rejetés d'une publication modifiée, source comprise.

**Valeurs dérivées recalculées en entier.** `usage_count` et la vue des co-occurrences se recalculent à chaque passage depuis les liens non rejetés, sans état conservé entre deux exécutions.

**Sujets sans lien.** Un sujet qu'aucun lien ne porte est supprimé ; un sujet dont tous les liens sont rejetés subsiste, pour ne pas perdre la décision humaine.
