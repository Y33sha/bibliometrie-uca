# Chantier — Typage strict des projections de lecture

## Contexte

Le chantier `CODE_chasse-aux-any` a verrouillé `disallow_any_explicit` et `disallow_any_generics` globalement. Subsistent des types « bâtards » documentés et désactivés par module dans `pyproject.toml`, qui mériteraient un sweep dédié :

- **`Row[Any]`** (28 occ.) — surtout signatures `process_work` des normalizers et retours de queries SA `.one()/.all()`. Le `[Any]` neutralise la vérification du contenu de la row alors qu'on sait quels champs sont sélectionnés.
- **`list[dict[str, Any]]`** (130 occ.) — mélange hétérogène : listes de records DB hydratés en dict, batchs SQL `executemany` à valeurs hétérogènes, listes JSON externes.
- **`fields: dict[str, Any]`** (6 occ.) — partial updates côté ports repository (`update_*_fields`). Les colonnes possibles sont connues du port mais pas exprimées dans le type.

Le chantier `CODE_rich-domain-model` Phase 8 couvre déjà l'hydratation des entités (records DB → aggregate riche). Le présent chantier est complémentaire : il s'intéresse au **typage strict des projections** quand on choisit délibérément de ne pas hydrater une entité complète (record minimal, batch SQL, partial update).

## Décisions

À instruire au démarrage. Hypothèses de travail :

1. **Pas une hydratation systématique** : si une méthode retourne 2-3 colonnes pour usage immédiat, pas la peine de fabriquer une entité — un `NamedTuple` ou `TypedDict` suffit. Le critère « entité riche vs projection » se tranche au cas par cas selon ce que le caller en fait.
2. **`NamedTuple` vs `TypedDict` vs `dataclass(frozen)`** : à trancher. `NamedTuple` est immutable et indexable, `TypedDict` ne fabrique pas d'objet (zero-cost), `dataclass` est plus expressif (defaults, validators). Probablement pas un seul choix global.
3. **Partial updates** : `TypedDict(total=False)` par port (`JournalUpdateFields`, `PerimeterUpdateFields`, etc.) — déjà inscrit en `rich-domain-model` Phase 8, à reprendre ici si on tranche que ce chantier l'absorbe.
4. **Batchs SQL hétérogènes** (`normalize_wos` notamment) : décomposer par batch (`WosAddressBatch`, `WosAuthorshipBatch`, …) avec un dataclass ou TypedDict par contrat.

## Phasage

À instruire. Esquisse :

- **Audit** : inventaire des 28 `Row[Any]` + 130 `list[dict[str, Any]]` + 6 `fields: dict[str, Any]`, classifiés par catégorie (record DB / batch SQL / liste JSON / etc.) et par fréquence d'usage.
- **Décision de pattern** par catégorie (cf. Décisions ci-dessus).
- **Sweep par couche** : domain ports → application ports → infrastructure adapters → application services.
- **Retrait progressif des modules** correspondants de l'override de désactivation `disallow_any_explicit = false` dans `pyproject.toml`.

## Questions ouvertes

- **Périmètre vs `CODE_rich-domain-model` Phase 8** : Phase 8 traite des records DB → entité riche pour les aggregates principaux (Person, Structure, SourcePublication, AddressAffiliation). Ce chantier-ci traite des **projections** (records minimaux, batchs, partial updates) — distinct mais avec chevauchement (`fields: dict[str, Any]` apparaît dans les deux). À recadrer au démarrage.
- **`Row[Any]` vs `Row[tuple[type1, type2, ...]]`** : la version paramétrée est précise mais fragile (changement de SELECT → type cassé sans erreur runtime). Décision pragmatique probable : `NamedTuple` par requête plutôt que `Row` paramétré.
- **Coût/bénéfice par cas** : certains `Row[Any]` ne valent pas le typage (résultat lu une fois sur place, `.scalar_one()`). Un critère « > 2 colonnes ou propagé hors de la fonction » est probablement le bon seuil.

## Liens

- Préalable : `2026-05-XX_CODE_chasse-aux-any.md` (verrou global posé, modules avec `Any` documentés en désactivation).
- Chevauche : `CODE_rich-domain-model.md` Phase 8 (hydratation entités côté `domain/ports/*_repository.py`).
