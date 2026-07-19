# Typage des paramètres de requête : ce que `str` ne dit pas

## Contexte

Une query string ne transporte que du texte. C'est l'annotation d'un paramètre FastAPI qui dit comment le lire : déclarer `bool` fait accepter `true/false/1/0/on/off/yes/no` et refuser le reste par un 422 ; déclarer `Literal[...]` restreint au vocabulaire et le publie dans le contrat OpenAPI ; déclarer `list[str]` lit un paramètre répété. Le typage est ce qui valide, ce qui documente et ce qui convertit.

Les routers déclarent pourtant `str` une centaine de fois, y compris là où le vocabulaire est connu. Trois familles s'y confondent.

**Les tri-états.** `has_orcid`, `has_idhal`, `has_idref`, `has_rh`, `has_pending_forms`, `has_pending_identifiers` (personnes) et `has_country` (adresses) portent trois états — filtrer sur oui, filtrer sur non, ne pas filtrer — encodés `"yes"` / `"no"` / `""` dans une chaîne unique. La forme typée existe et le projet la pratique ailleurs : `journals.py` déclare `is_in_doaj: bool | None = None`, où le paramètre absent vaut `None`.

**Les vocabulaires fermés.** `validation` (`all`, `pending`, `confirmed`, `rejected`) et `detected` (`all`, `yes`, `no`) : des énumérations à valeur unique, qu'un `Literal` déclarerait. `detected` en est bien une et non un tri-état : `all` est une valeur émise, que l'absence du paramètre ne saurait porter puisque le défaut vaut `yes`.

`access` et `hal_status` en ont l'air et n'en sont pas : ils passent par `parse_str_csv` et le frontend émet `access=oa,closed`. Ce sont des listes dont les éléments viennent d'un vocabulaire fermé — un `Literal` sur la chaîne les refuserait.

`sort` relève de la même famille, dans les cinq listes paginées — éditeurs, revues, publications, et les personnes qui en ont deux, l'annuaire et la liste de curation. Chacune a son vocabulaire fermé, et sa table d'ordonnancement retombe en silence sur le tri par défaut devant une valeur inconnue (`_SORT_MAP.get(sort, défaut)`). Un `Literal` par liste les déclarerait. La faute y coûte moins cher qu'ailleurs : un tri inconnu rend le bon ensemble dans le mauvais ordre, là où un filtre inconnu rend le mauvais ensemble.

**Les listes.** `department`, `role`, `year`, `doc_type`, `country`, `oa_status`, `access`, `hal_status`, `lab_id`, `source_filter` transportent plusieurs valeurs séparées par des virgules, que `parse_str_csv` découpe. Cette écriture en valeurs séparées par des virgules — sans rapport avec l'export en fichier CSV, qui reçoit d'ailleurs exactement les mêmes paramètres que la liste qu'il reproduit — est délibérée et se défend ; elle n'est pas en cause ici.

**Les prédicats composés.** `text` et `struct` (adresses) sont des paramètres répétés dont chaque occurrence porte une micro-syntaxe `<opérateur>:<charge>` — `text=contains:inserm`, `struct=not_recognized:12,14`. Déclarés `list[str]`, ils échappent entièrement à FastAPI : c'est `_parse_text_predicates` et `_parse_structure_predicates` qui découpent, valident l'opérateur contre un ensemble en dur et construisent les objets-valeurs. Les deux fonctions écrivent la même décision, et la documentent chacune de leur côté : un opérateur inconnu ou une charge vide fait tomber le prédicat au lieu de refuser la requête. `?struct=recognized:abc` ne filtre donc rien, et la page affiche l'ensemble complet sans que rien ne le signale — le symptôme des tri-états, sous une autre syntaxe.

`is_corresponding`, `has_apc` et `in_perimeter` (publications) ressemblent à des tri-états et n'en sont pas : ce sont des **facettes multi-sélection sur une dimension binaire**, une liste de `yes` / `no` combinée en OR par `_person_toggle_clause`. Cocher les deux ne contraint rien, ne rien cocher non plus. Ils relèvent des listes, et un booléen les trahirait.

Les deux premières familles paient le même prix.

**La validation disparaît.** `?has_orcid=banana` ne déclenche aucun 422 : `person_has_identifier_clause` fait `if value not in ("yes", "no"): return None`. Le filtre est silencieusement ignoré, et la liste rendue n'est pas celle qu'on croit. Une faute de frappe ne se voit nulle part.

**La conversion se réécrit à la main.** `_has_country_flag` (`services/addresses/countries.py`) ne fait rien d'autre que retraduire `"yes" → True`, `"no" → False`, autre → `None` — le travail que l'annotation ferait. Trois modules décodent ainsi le même vocabulaire.

**Le contrat ment.** Le schéma TypeScript annonce `string` là où trois valeurs seulement ont un sens, et le frontend émet `"yes"` / `"no"` en quatorze endroits sans que rien ne le tienne.

## Décisions

**Les tri-états deviennent `bool | None = None`.** L'absence du paramètre vaut « ne pas filtrer », `true` et `false` valent les deux filtres. La validation revient à FastAPI, la conversion disparaît, et le contrat publie un booléen. Les décodeurs `"yes"` / `"no"` — `_has_country_flag` et ses voisins — n'ont plus d'objet ; les clauses reçoivent directement `bool | None`.

Le frontend n'a rien à changer. Il omet déjà le paramètre pour ne pas filtrer (`if (…length === 1) params.set(…)`), et Pydantic lit `yes` et `no` comme des booléens. Le seul écart de comportement porte sur une valeur explicitement vide, `?has_orcid=`, aujourd'hui ignorée en silence et refusée ensuite par un 422 — qu'aucun appelant n'émet.

**Les vocabulaires fermés deviennent des `Literal`.** Le jeu de valeurs se déclare une fois, le 422 tombe sur l'intrus, et le contrat TypeScript rend une union plutôt qu'une chaîne. Là où le domaine porte déjà le vocabulaire, le `Literal` en vient.

**Les listes à valeurs séparées par des virgules restent.** La convention est en place, documentée, et partagée par les pages à facettes ; elle ne coûte pas de validation perdue, `parse_str_csv` n'ayant rien à refuser.

**Les prédicats composés gardent leur syntaxe et perdent leur silence.** L'opérateur se déclare en énumération, et un prédicat malformé est refusé au lieu d'être abandonné. Les deux parsers ne se factorisent pas l'un dans l'autre : leur forme commune tient en une boucle de huit lignes, et la partager supposerait une fonction paramétrée par un ensemble d'opérateurs, un parseur de charge et une fabrique — trois indirections pour deux appelants. C'est la règle de tolérance, écrite deux fois, qui est le doublon à traiter, non le découpage.

## Phasage

### Phase 1 — les tri-états

Sept paramètres : `has_orcid`, `has_idhal`, `has_idref`, `has_rh`, `has_pending_forms`, `has_pending_identifiers` (personnes) et `has_country` (adresses).

- [x] Les champs des dataclasses de filtres passent à `bool | None` ; les quatre clauses SQL suivent, et leur garde `if value not in ("yes", "no")` devient `if value is None`.
- [x] Les routers déclarent `bool | None = None`. `_has_country_flag` disparaît : le corps de `batch-country` porte le même vocabulaire que la query string et se type de même, si bien que la conversion n'a plus de site où vivre.
- [x] Contrat TypeScript régénéré : les sept paramètres passent de `string` à `boolean | null`. `svelte-check` reste à zéro erreur sans qu'une ligne de frontend ait bougé, ce qui vérifie la prédiction.

### Phase 2 — les vocabulaires fermés

- [x] `sort` : les cinq vocabulaires s'alignent sur `<champ>_asc` / `<champ>_desc`. Quatre écrivaient le sens descendant en préfixe (`-name`), où le croissant se lisait à l'**absence** du tiret — une convention dont un terme est implicite se prête mal à un `Literal`, qui doit tout énumérer. Le cinquième, celui des publications, n'appliquait pas la sienne : `title` y côtoyait `title_desc`. Les helpers génériques du frontend suivent (`oppositeSort`, indicateurs de colonne).
- [x] `validation` et `detected` : les valeurs honorées par l'adaptateur des adresses sont `all`/`pending`/`confirmed`/`rejected` et `all`/`yes`/`no`, `all` valant absence de clause.
- [x] Sept vocabulaires déclarés en `Literal` auprès des lectures qu'ils paramètrent — cinq tris dans leurs ports respectifs, les deux états d'adresse dans le leur. Les adaptateurs les importent pour typer leurs signatures, si bien que mypy refuse une table d'ordonnancement dont une clé sortirait du vocabulaire.
- [x] Les cinq replis `_SORT_MAP.get(sort, défaut)` deviennent des indexations directes : FastAPI garantit désormais que la valeur appartient au vocabulaire, et le défaut silencieux n'a plus de cas à traiter. Deux tests attestaient ce repli ; ils attestent maintenant le 422.

### Phase 3 — les prédicats composés

- [x] Vérification préalable : la page des adresses n'émet jamais de prédicat malformé. Elle n'ajoute une occurrence `text` que si le terme est non vide, une occurrence `struct` que si la liste d'identifiants l'est aussi, et son mode comme son opérateur viennent d'unions typées.
- [x] Les opérateurs se déclarent en `Literal` au port, et les dataclasses `TextPredicate` et `StructurePredicate` les portent à la place de `str`.
- [x] La forme entière se déclare au router par un motif posé sur chaque occurrence répétée (`list[Annotated[str, Query(pattern=...)]]`). FastAPI refuse alors l'occurrence malformée par un 422 et publie le motif dans le contrat OpenAPI, sans contrôle écrit à la main. Les deux parseurs se réduisent à un découpage, et leur règle de tolérance — la même décision écrite deux fois — disparaît avec ce qu'elle traitait.

  La page des adresses garde sa propre lecture de ces prédicats (`parseTextParam`, `parseStructParam`), et c'est justifié : elle relit une query string qu'un utilisateur a pu modifier à la main, et doit en restaurer ce qu'elle peut plutôt que rompre. Sa tolérance n'est donc pas la décision que le serveur vient d'abandonner. Reste en commun le vocabulaire — quatre chaînes — qu'un type généré ne peut pas lui transmettre, `openapi-typescript` rendant `string[]` pour un paramètre dont la contrainte est un motif.

## Questions ouvertes

- **Les éléments des listes à vocabulaire fermé.** `access`, `hal_status`, `oa_status` et `doc_type` transportent des valeurs prises dans un ensemble connu, qu'aucune validation ne contrôle : leur écriture en une chaîne unique les rend opaques à FastAPI. Les valider supposerait soit un contrôle après découpage, soit le passage à des paramètres répétés typés `list[Literal[...]]`, qui change la forme des URL et donc le frontend. À instruire séparément.
- **Ce que le 422 change pour le frontend.** Les valeurs hors vocabulaire sont aujourd'hui ignorées en silence ; après, elles seront refusées. À vérifier : aucune page n'émet une valeur que l'adapter ignore et dont elle dépendrait.
