# Chantier — Relations entre publications

Stub. Modélisation des relations entre entités `publications` qui ne sont pas des doublons mais qui sont liées sémantiquement : parent ↔ supplément, ouvrage ↔ chapitre, version ↔ révision, article ↔ erratum/retraction, conférence ↔ poster, dataset ↔ article qui l'utilise.

## Contexte

Trigger immédiat : **suppléments orphelins figshare** identifiés dans [METIER_doc-types](METIER_doc-types.md). Au 2026-05-05, 145 cas de DOI figshare classés `dataset` (post-correction `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`) dont le titre référence un article parent qui n'est pas en BDD. Hypothèses à tester par sondage :

- (a) parent présent avec un titre légèrement différent (matching à raffiner)
- (b) parent réellement absent et c'est correct (publi non-UCA)
- (c) parent réellement absent à tort (à retrouver)

Cas connexes qui motiveraient le même modèle :

- **Figshare collections** (`10.6084/m9.figshare.c.*`) : bundles agrégeant plusieurs items. À auditer : combien de cas, à quoi sont-ils rattachables (article parent, dataset multi-fichiers, …).
- **Posters et conférence avec même DOI** : sondage à faire, ne pas fusionner aveuglément en dédup.
- **Article ↔ erratum/retraction** : aujourd'hui chacun est une publication indépendante avec son propre DOI ; le lien sémantique est perdu.
- **Ouvrage ↔ chapitre** : déjà présents séparément ; pas de lien explicite.

## Périmètre

À définir une fois les sondages faits. Pistes :

- Table `publication_relations` avec `(parent_id, child_id, relation_type, source)` ?
- Colonne JSONB `publications.related` ?
- Stockage côté `source_publications` (relation observée par source) + agrégation canonique ?

## Open questions

- Cardinalité (1-N, N-N) selon relation_type ?
- Effet sur l'UI (afficher les liés dans la fiche publication) ?
- Effet sur la dédup (un supplément orphelin marqué comme tel doit-il être éliminé du périmètre ou conservé avec un flag) ?
- Sources qui exposent ces relations nativement : CrossRef `relation`, DataCite `relatedIdentifiers`, OpenAlex (parfois `referenced_works`) — comment les ingérer ?

## Préalable

Audit des cas connus avant toute modélisation. Au minimum :

- Compter les orphelins figshare et sonder leurs titres (parent retrouvable par matching titre ?).
- Compter les collections figshare et leur classification actuelle.
- Compter les paires erratum/article qui partagent un préfixe DOI (heuristique faible mais informative).
