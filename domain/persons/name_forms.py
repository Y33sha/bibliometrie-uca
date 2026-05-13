"""Value object `PersonNameForm` + factory `compute_person_name_forms`
+ helpers pour la colonne `persons` JSONB.

Une forme de nom est une représentation normalisée d'une combinaison
(last_name, first_name) destinée au matching. Plusieurs formes par
personne : « prenom nom », « nom prenom », formes initialisées, etc.
(cf. `compute_person_name_forms` ci-dessous).

Du point de vue domain, une forme de nom est entièrement définie par
sa string normalisée — VO immuable, égalité par valeur.

Note storage : la table `person_name_forms` (`name_form text + persons
jsonb`) est un **index inverse** dénormalisé pour le matching nom →
personnes, pas un aggregate. La colonne `persons` porte le mapping
`{ "<person_id>": ["<source1>", ...] }` qui couple chaque person_id à
ses sources observées ; les helpers `add_person_source` /
`remove_person_source` / `merge` / etc. centralisent les manipulations
de ce dict pour que la connaissance du format ne se répande pas en SQL
inline.
"""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import normalize_name


@dataclass(frozen=True)
class PersonNameForm:
    """Forme normalisée du nom d'une personne (VO).

    Identité = la string normalisée. La normalisation préalable est
    portée par `compute_person_name_forms` ; le VO se contente de
    garantir la non-vacuité.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValidationError("PersonNameForm ne peut pas être vide")

    def __str__(self) -> str:
        return self.value


# ── Factory de formes ──────────────────────────────────────────────


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les variantes normalisées de formes de nom pour une personne.

    Règle de composition du domaine (ne dépend d'aucune BD). Les
    strings retournées sont les valeurs canoniques d'instances de
    `PersonNameForm`.

    Retourne un ensemble de formes normalisées :
      - "prenom nom", "nom prenom"
      - "initiale(s) nom", "nom initiale(s)"
        Si le prénom a plusieurs mots (ex: "jean michel"), produit :
        - initiales séparées : "j m nom", "nom j m"
        - initiales collées  : "jm nom", "nom jm"
    """
    ln = normalize_name(last_name)
    fn = normalize_name(first_name)
    if not ln:
        return set()

    forms: set[str] = set()
    if fn:
        forms.add(f"{fn} {ln}")
        forms.add(f"{ln} {fn}")

        parts = fn.split()
        if parts:
            initials_spaced = " ".join(p[0] for p in parts)
            initials_joined = "".join(p[0] for p in parts)
            forms.add(f"{initials_spaced} {ln}")
            forms.add(f"{ln} {initials_spaced}")
            if initials_joined != initials_spaced:
                forms.add(f"{initials_joined} {ln}")
                forms.add(f"{ln} {initials_joined}")
    else:
        forms.add(ln)

    return forms


# ── Helpers pour la colonne `persons` JSONB ────────────────────────
#
# Format : `dict[str, list[str]]` où la clé est `str(person_id)` (les
# clés JSON sont nécessairement des strings) et la valeur la liste des
# sources observées, dédupliquée et triée pour stabilité.
#
# Toutes les fonctions sont pures : elles retournent un nouveau dict
# sans muter l'argument. Le tri systématique garantit que deux dicts
# sémantiquement équivalents ont la même représentation (utile pour
# les diffs).

PersonsDict = dict[str, list[str]]


def add_person_source(persons: PersonsDict, person_id: int, source: str) -> PersonsDict:
    """Ajoute `source` aux sources de `person_id`. Crée la clé si absente."""
    key = str(person_id)
    merged = sorted(set(persons.get(key, [])) | {source})
    return {**persons, key: merged}


def remove_person_source(persons: PersonsDict, person_id: int, source: str) -> PersonsDict:
    """Retire `source` des sources de `person_id`.

    Supprime la clé si la liste devient vide. No-op si la clé est absente.
    """
    key = str(person_id)
    if key not in persons:
        return dict(persons)
    remaining = [s for s in persons[key] if s != source]
    result = {k: list(v) for k, v in persons.items() if k != key}
    if remaining:
        result[key] = remaining
    return result


def remove_person(persons: PersonsDict, person_id: int) -> PersonsDict:
    """Retire entièrement la clé `person_id`. No-op si absente."""
    key = str(person_id)
    return {k: list(v) for k, v in persons.items() if k != key}


def merge(a: PersonsDict, b: PersonsDict) -> PersonsDict:
    """Union par clé. Pour chaque clé partagée, sources mergées triées."""
    keys = set(a) | set(b)
    return {k: sorted(set(a.get(k, [])) | set(b.get(k, []))) for k in keys}


def is_ambiguous(persons: PersonsDict) -> bool:
    """True si >1 person_id référencé (forme partagée)."""
    return len(persons) > 1


def person_ids(persons: PersonsDict) -> list[int]:
    """Liste triée des `person_id` (clés str → int)."""
    return sorted(int(k) for k in persons)


def all_sources(persons: PersonsDict) -> list[str]:
    """Union triée des sources, toutes personnes confondues."""
    union: set[str] = set()
    for sources in persons.values():
        union.update(sources)
    return sorted(union)
