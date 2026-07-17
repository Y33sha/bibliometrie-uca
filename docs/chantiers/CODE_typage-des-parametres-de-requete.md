# Typage des paramètres de requête : ce que `str` ne dit pas

## Contexte

Une query string ne transporte que du texte. C'est l'annotation d'un paramètre FastAPI qui dit comment le lire : déclarer `bool` fait accepter `true/false/1/0/on/off/yes/no` et refuser le reste par un 422 ; déclarer `Literal[...]` restreint au vocabulaire et le publie dans le contrat OpenAPI ; déclarer `list[str]` lit un paramètre répété. Le typage est ce qui valide, ce qui documente et ce qui convertit.

Les routers déclarent pourtant `str` une centaine de fois, y compris là où le vocabulaire est connu. Trois familles s'y confondent.

**Les tri-états.** `has_orcid`, `has_idhal`, `has_idref`, `has_rh`, `has_pending_forms`, `has_pending_identifiers` (personnes) et `has_country` (adresses) portent trois états — filtrer sur oui, filtrer sur non, ne pas filtrer — encodés `"yes"` / `"no"` / `""` dans une chaîne unique. La forme typée existe et le projet la pratique ailleurs : `journals.py` déclare `is_in_doaj: bool | None = None`, où le paramètre absent vaut `None`.

**Les vocabulaires fermés.** `validation` (`all`, `pending`, `confirmed`, `rejected`), `detected` (`all`, `yes`, `no`), `access`, `hal_status` : des énumérations, qu'un `Literal` déclarerait.

**Les listes.** `department`, `role`, `year`, `doc_type`, `country`, `oa_status`, `lab_id`, `source_filter` transportent plusieurs valeurs séparées par des virgules, que `parse_str_csv` découpe. La convention CSV est délibérée et se défend ; elle n'est pas en cause ici.

`is_corresponding`, `has_apc` et `in_perimeter` (publications) ressemblent à des tri-états et n'en sont pas : ce sont des **facettes multi-sélection sur une dimension binaire**, une liste de `yes` / `no` combinée en OR par `_person_toggle_clause`. Cocher les deux ne contraint rien, ne rien cocher non plus. Ils relèvent des listes, et un booléen les trahirait.

Les deux premières familles paient le même prix.

**La validation disparaît.** `?has_orcid=banana` ne déclenche aucun 422 : `person_has_identifier_clause` fait `if value not in ("yes", "no"): return None`. Le filtre est silencieusement ignoré, et la liste rendue n'est pas celle qu'on croit. Une faute de frappe ne se voit nulle part.

**La conversion se réécrit à la main.** `_has_country_flag` (`services/addresses/countries.py`) ne fait rien d'autre que retraduire `"yes" → True`, `"no" → False`, autre → `None` — le travail que l'annotation ferait. Trois modules décodent ainsi le même vocabulaire.

**Le contrat ment.** Le schéma TypeScript annonce `string` là où trois valeurs seulement ont un sens, et le frontend émet `"yes"` / `"no"` en quatorze endroits sans que rien ne le tienne.

## Décisions

**Les tri-états deviennent `bool | None = None`.** L'absence du paramètre vaut « ne pas filtrer », `true` et `false` valent les deux filtres. La validation revient à FastAPI, la conversion disparaît, et le contrat publie un booléen. Les décodeurs `"yes"` / `"no"` — `_has_country_flag` et ses voisins — n'ont plus d'objet ; les clauses reçoivent directement `bool | None`.

**Les vocabulaires fermés deviennent des `Literal`.** Le jeu de valeurs se déclare une fois, le 422 tombe sur l'intrus, et le contrat TypeScript rend une union plutôt qu'une chaîne. Là où le domaine porte déjà le vocabulaire, le `Literal` en vient.

**Les listes CSV restent.** La convention est en place, documentée, et partagée par les pages à facettes ; elle ne coûte pas de validation perdue, `parse_str_csv` n'ayant rien à refuser.

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
- [ ] Vérifier ce qu'une valeur hors vocabulaire produit aujourd'hui, avant qu'elle produise un 422.

## Questions ouvertes

- **Le défaut de `detected`.** Il vaut `"yes"`, non `""` : l'absence du paramètre filtre. Un `bool | None = True` le dirait, au prix d'un défaut qui n'est pas « ne pas filtrer » — à distinguer des tri-états dont l'absence n'a pas de sens métier.
- **Ce que le 422 change pour le frontend.** Les valeurs hors vocabulaire sont aujourd'hui ignorées en silence ; après, elles seront refusées. À vérifier : aucune page n'émet une valeur que l'adapter ignore et dont elle dépendrait.
