# Chantier — Matching cross-source des authorships

Commencé le 2026-05-30

## Contexte

Sur une publication présente dans plusieurs sources, un auteur UCA peut être correctement identifié par certaines sources mais pas par d'autres : l'authorship canonique reçoit un `person_id` via la source qui détecte UCA, mais les `source_authorships` des autres sources restent orphelines (`person_id = NULL`, `authorship_id = NULL`).

Cas concret repéré à l'usage — publication 165072, 28 auteurs, présente dans HAL / OpenAlex / CrossRef :

- HAL : Alexandre Janel (position 6) et Thomas Tassin (position 17) ont `in_perimeter = TRUE`, `person_id` rempli, `authorship_id` rempli.
- OpenAlex et CrossRef : aux mêmes positions, mêmes noms (`elise sourdeau`, `franck genevieve`, …, `alexandre janel`, …), mais `in_perimeter = FALSE`, `person_id = NULL`, `authorship_id = NULL`.

Cause mécanique : la phase persons charge ses candidats via `fetch_unlinked_authorships` ([infrastructure/queries/persons/create.py:44-45](infrastructure/queries/persons/create.py#L44-L45)), qui filtre sur `sa.in_perimeter = TRUE`. Une SA hors-périmètre n'entre jamais dans la cascade de matching, donc ne reçoit jamais de `person_id`, donc ne se relie jamais à l'authorship canonique en étape 2 de `build_authorships`.

Pourquoi les SA OA/CrossRef restent `in_perimeter = FALSE` alors que HAL les marque UCA : la phase `affiliations` pose `in_perimeter` source par source, sur détection textuelle d'affiliation UCA. Quand HAL est bien renseigné (signature UCA propre) mais OA/CrossRef ne voient qu'une affiliation tierce (cas typique : auteur UCA-CHU qui signe seulement CHU dans OA), les sources divergent sur le statut périmètre du même auteur.

L'étape 4 de `build_authorships` propage `in_perimeter` à l'**authorship canonique** (union des sources) — donc le compteur `authorships.in_perimeter` reste cohérent. Le trou est en amont : le filtre `sa.in_perimeter = TRUE` court-circuite la résolution `person_id` pour les SA qui pourraient être rattachées via le mécanisme cross-source de la cascade (étape 4 de `decide_person_match`).

### Audit volume initial

Par source manquante, sur les publications où au moins une autre source a déjà un `person_id` à la même position :

| Source manquante | Total (position match) | Nom normalisé identique |
|---|---|---|
| crossref | 35 990 | 27 097 (75 %) |
| scanr    | 29 038 | 27 505 (95 %) |
| wos      | 13 741 |     24 (0,2 %) |
| openalex |  9 966 |  4 498 (45 %) |
| hal      |  8 311 |  4 906 (59 %) |
| theses   |     77 |     76        |

~64 000 SA rattachables mécaniquement à un `person_id` existant (égalité de `author_name_normalized`). WoS est l'exception : sa représentation des noms (initiales prénom + casse) défait l'égalité normalisée — pour WoS il faut un matching plus tolérant si on veut couvrir le volume.

Après filtre méga-papers (publis dont le max d'auteurs par source ≤ 50, aligné sur `MAX_AUTHORS_CROSS_SOURCE` de la cascade existante), les volumes effectifs descendent à : crossref 22 903, scanr 25 182, openalex 3 959, hal 4 550, theses 75, wos 12. Total ~56 700 SA candidates au rattachement trivial. Le reste des compteurs initiaux était dominé par des méga-papers physique des particules où les positions divergent entre sources et le matching `(pub, position)` cesse d'être discriminant.

## Décisions

- **Lecture seule d'abord** : avant tout fix, on consolide l'audit. Le volume actuel (~64 k SA candidates au rattachement, ~33 k de plus avec position match mais nom non strictement identique) doit être qualifié à l'œil sur un sample pour mesurer le taux de faux positifs avant un éventuel oneshot d'application.
- **Critère "position compatible" strict** au démarrage : même position exacte uniquement, comme la cascade existante (`decide_cross_source_match`). On élargira (tolérance ±N, ou alignement par nom) plus tard si l'audit qualitatif justifie l'ouverture.
- **`source_authorships.in_perimeter` n'est pas touché** par un éventuel fix : la valeur reflète honnêtement la détection par chaque source. Un auteur UCA-CHU qui ne signe que CHU dans OpenAlex doit rester `in_perimeter = FALSE` côté SA OA — cette information est exploitable (signal de signature dégradée pour cet auteur sur cette publication). Seuls `person_id` et `authorship_id` sont à compléter côté SA.
- **L'authorship canonique reste la table de vérité** pour `in_perimeter` (déjà union des sources via build_authorships étape 4). Pas de modification de cette logique.

## Phasage

### Phase 1 — Audit read-only consolidé
- [x] Oneshot [interfaces/cli/oneshot/audit_authorships_cross_source.py](../../interfaces/cli/oneshot/audit_authorships_cross_source.py) : compteurs (avec / sans filtre méga-papers) + échantillon de ~20 cas par source (méga-papers exclus) à valider à l'œil (publi + position + nom de référence + nom orphelin).

### Phase 2 — Oneshot d'application
- [x] Étend la cascade `decide_person_match` étape 4 (cross-source par publi + position) aux SA `in_perimeter = FALSE` quand au moins une autre SA de la même publi est déjà reliée à un `person_id`. UPDATE de `source_authorships.person_id` + `authorship_id` ; `source_authorships.in_perimeter` non modifié.

### Phase 3 — Intégration permanente dans la phase persons
Le oneshot Phase 2 est une application ponctuelle : sans intégration, la lacune réapparaît sur chaque nouvelle publi. On rend la passe cross-source permanente.

- [ ] Passe dédiée **en fin de phase persons**, après la cascade normale (les ancres `person_id` doivent déjà exister sur la publi).
- [ ] Requête **scopée** : SA `in_perimeter = FALSE`, `person_id IS NULL`, sur une publi ayant ≥1 SA déjà reliée à la même position. Borne le coût (~quelques 10 k, pas le pool mondial non-UCA) et décroît à chaque run, comme le modèle « non-relié » actuel — pas de flag dirty à introduire.
- [ ] Réutiliser la logique du oneshot Phase 2 (`decide_person_match` étape 4) — factoriser, pas dupliquer.
- [ ] `source_authorships.in_perimeter` non touché ; seuls `person_id` + `authorship_id` complétés (cf. Décisions).
- [ ] Mesurer le coût ajouté à la phase persons (doit rester négligeable vu le scope).

Forward-compatible avec une éventuelle refonte « record linkage personnes » : l'arête cross-source (même publi + position + nom compatible, ancrée sur une personne existante) est conservatrice et survivrait à un changement de modèle. Cette refonte — linkage *homonyme-aware*, car les noms de personnes ne sont pas des clés quasi-uniques comme le sont DOI / metadata_block côté publications — est un chantier distinct, hors scope ici.

## Questions ouvertes

- **Exposition UI** : l'audit Phase 1 serait-il utile à l'admin (vue « publications avec authorship incomplet par source ») ? À arbitrer après la Phase 3. (Conflits de source => peut servir à la détection de fusions erronées de publications.)

## Liens

- Phase persons : [docs/pipeline/08-persons.md](../pipeline/08-persons.md)
- Code matching : [application/pipeline/persons/create_persons_from_source_authorships.py](../../application/pipeline/persons/create_persons_from_source_authorships.py)
- Query filtre périmètre : [infrastructure/queries/persons/create.py:44-45](../../infrastructure/queries/persons/create.py#L44-L45)
- Étape 2 de build_authorships (peuplement FK `source_authorships.authorship_id`) : [application/pipeline/authorships/build_authorships.py:69-72](../../application/pipeline/authorships/build_authorships.py#L69-L72)
