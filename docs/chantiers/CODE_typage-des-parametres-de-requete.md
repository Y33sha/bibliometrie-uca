# Typage des paramètres de requête : ce que `str` ne dit pas

## Contexte

Une query string ne transporte que du texte. C'est l'annotation d'un paramètre FastAPI qui dit comment le lire : déclarer `bool` fait accepter `true/false/1/0/on/off/yes/no` et refuser le reste par un 422 ; déclarer `Literal[...]` restreint au vocabulaire et le publie dans le contrat OpenAPI ; déclarer `list[str]` lit un paramètre répété. Le typage est ce qui valide, ce qui documente et ce qui convertit.

Les routers déclarent pourtant `str` une centaine de fois, y compris là où le vocabulaire est connu. Trois familles s'y confondent.

**Les tri-états.** `has_orcid`, `has_idhal`, `has_idref`, `has_rh`, `has_pending_forms`, `has_pending_identifiers` (personnes) et `has_country` (adresses) portent trois états — filtrer sur oui, filtrer sur non, ne pas filtrer — encodés `"yes"` / `"no"` / `""` dans une chaîne unique. La forme typée existe et le projet la pratique ailleurs : `journals.py` déclare `is_in_doaj: bool | None = None`, où le paramètre absent vaut `None`.

**Les vocabulaires fermés.** `validation` (`all`, `pending`, `confirmed`, `rejected`), `detected` (`all`, `yes`, `no`), `access`, `hal_status` : des énumérations, qu'un `Literal` déclarerait.

`sort` relève de la même famille, dans les quatre listes paginées — éditeurs, revues, personnes, publications. Chacune a son vocabulaire fermé, et sa table d'ordonnancement retombe en silence sur le tri par défaut devant une valeur inconnue (`_SORT_MAP.get(sort, défaut)`). Deux conventions y cohabitent sans que rien ne le signale : le sens descendant s'écrit en préfixe pour les trois premières (`-name`), en suffixe pour les publications (`year_desc`, `title_desc`). Un `Literal` par liste les déclarerait, et rendrait l'écart visible. La faute y coûte moins cher qu'ailleurs : un tri inconnu rend le bon ensemble dans le mauvais ordre, là où un filtre inconnu rend le mauvais ensemble.

**Les listes.** `department`, `role`, `year`, `doc_type`, `country`, `oa_status`, `lab_id`, `source_filter` transportent plusieurs valeurs séparées par des virgules, que `parse_str_csv` découpe. La convention CSV est délibérée et se défend ; elle n'est pas en cause ici.

**Les prédicats composés.** `text` et `struct` (adresses) sont des paramètres répétés dont chaque occurrence porte une micro-syntaxe `<opérateur>:<charge>` — `text=contains:inserm`, `struct=not_recognized:12,14`. Déclarés `list[str]`, ils échappent entièrement à FastAPI : c'est `_parse_text_predicates` et `_parse_structure_predicates` qui découpent, valident l'opérateur contre un ensemble en dur et construisent les objets-valeurs. Les deux fonctions écrivent la même décision, et la documentent chacune de leur côté : un opérateur inconnu ou une charge vide fait tomber le prédicat au lieu de refuser la requête. `?struct=recognized:abc` ne filtre donc rien, et la page affiche l'ensemble complet sans que rien ne le signale — le symptôme des tri-états, sous une autre syntaxe.

`is_corresponding`, `has_apc` et `in_perimeter` (publications) ressemblent à des tri-états et n'en sont pas : ce sont des **facettes multi-sélection sur une dimension binaire**, une liste de `yes` / `no` combinée en OR par `_person_toggle_clause`. Cocher les deux ne contraint rien, ne rien cocher non plus. Ils relèvent des listes, et un booléen les trahirait.

Les deux premières familles paient le même prix.

**La validation disparaît.** `?has_orcid=banana` ne déclenche aucun 422 : `person_has_identifier_clause` fait `if value not in ("yes", "no"): return None`. Le filtre est silencieusement ignoré, et la liste rendue n'est pas celle qu'on croit. Une faute de frappe ne se voit nulle part.

**La conversion se réécrit à la main.** `_has_country_flag` (`services/addresses/countries.py`) ne fait rien d'autre que retraduire `"yes" → True`, `"no" → False`, autre → `None` — le travail que l'annotation ferait. Trois modules décodent ainsi le même vocabulaire.

**Le contrat ment.** Le schéma TypeScript annonce `string` là où trois valeurs seulement ont un sens, et le frontend émet `"yes"` / `"no"` en quatorze endroits sans que rien ne le tienne.

## Décisions

**Les tri-états deviennent `bool | None = None`.** L'absence du paramètre vaut « ne pas filtrer », `true` et `false` valent les deux filtres. La validation revient à FastAPI, la conversion disparaît, et le contrat publie un booléen. Les décodeurs `"yes"` / `"no"` — `_has_country_flag` et ses voisins — n'ont plus d'objet ; les clauses reçoivent directement `bool | None`.

**Les vocabulaires fermés deviennent des `Literal`.** Le jeu de valeurs se déclare une fois, le 422 tombe sur l'intrus, et le contrat TypeScript rend une union plutôt qu'une chaîne. Là où le domaine porte déjà le vocabulaire, le `Literal` en vient.

**Les listes CSV restent.** La convention est en place, documentée, et partagée par les pages à facettes ; elle ne coûte pas de validation perdue, `parse_str_csv` n'ayant rien à refuser.

**Les prédicats composés gardent leur syntaxe et perdent leur silence.** L'opérateur se déclare en énumération, et un prédicat malformé est refusé au lieu d'être abandonné. Les deux parsers ne se factorisent pas l'un dans l'autre : leur forme commune tient en une boucle de huit lignes, et la partager supposerait une fonction paramétrée par un ensemble d'opérateurs, un parseur de charge et une fabrique — trois indirections pour deux appelants. C'est la règle de tolérance, écrite deux fois, qui est le doublon à traiter, non le découpage.

## Phasage

### Phase 1 — les tri-états

- [ ] Recenser les paramètres à trois états et leurs décodeurs (`filters.py`, `queries/api/addresses.py`, `services/addresses/countries.py`).
- [ ] Les champs des dataclasses de filtres passent à `bool | None` ; les clauses SQL suivent.
- [ ] Les routers déclarent `bool | None = None` ; les décodeurs disparaissent.
- [ ] Le frontend émet `true` / `false` et cesse d'envoyer le paramètre pour ne pas filtrer.
- [ ] Contrat TypeScript régénéré ; `svelte-check` couvre le changement de type.

### Phase 2 — les vocabulaires fermés

- [ ] `validation`, `detected`, `access`, `hal_status` : recenser les valeurs réellement honorées par les adapters.
- [ ] Les déclarer en `Literal`, en les tirant du domaine là où il les porte.
- [ ] `sort` des quatre listes paginées : un `Literal` par liste, et trancher si les deux conventions de sens descendant (préfixe contre suffixe) convergent.
- [ ] Vérifier ce qu'une valeur hors vocabulaire produit aujourd'hui, avant qu'elle produise un 422.

### Phase 3 — les prédicats composés

- [ ] Les opérateurs de `text` et `struct` se déclarent en énumération, à la place des ensembles en dur `_TEXT_MODES` et `_STRUCT_OPS`.
- [ ] Un prédicat malformé — opérateur inconnu, terme vide, liste d'identifiants sans chiffre — est refusé plutôt qu'abandonné.
- [ ] Vérifier d'abord ce que la page des adresses émet : elle construit ces paramètres elle-même, et un prédicat qu'elle produirait mal passerait aujourd'hui inaperçu.

## Questions ouvertes

- **Le défaut de `detected`.** Il vaut `"yes"`, non `""` : l'absence du paramètre filtre. Un `bool | None = True` le dirait, au prix d'un défaut qui n'est pas « ne pas filtrer » — à distinguer des tri-états dont l'absence n'a pas de sens métier.
- **Ce que le 422 change pour le frontend.** Les valeurs hors vocabulaire sont aujourd'hui ignorées en silence ; après, elles seront refusées. À vérifier : aucune page n'émet une valeur que l'adapter ignore et dont elle dépendrait.
