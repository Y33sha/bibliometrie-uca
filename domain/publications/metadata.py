"""Règles métier sur les métadonnées de publication — domain services
purs sans état d'instance.

Catch-all pour les règles qui touchent aux métadonnées d'une
publication (oa_status, titre canonique, …) et n'ont pas de meilleure
cible. À mesure qu'un type d'opération gagne en volume, il peut sortir
dans son propre module.
"""

import re
from collections.abc import Iterable

# ── Agrégation multi-sources du statut OA ───────────────────────────

# Classement des statuts OA : plus la valeur est grande, plus le
# statut est « ouvert ». Utilisé par `best_oa_status` pour choisir le
# statut le plus ouvert entre plusieurs sources.
OA_RANK: dict[str, int] = {
    "diamond": 7,
    "gold": 6,
    "hybrid": 5,
    "bronze": 4,
    "green": 3,
    "closed": 2,
    "unknown": 1,
}

# Valeur canonique de `publications.oa_status` quand aucune source n'a
# de signal exploitable. Convention : `source_publications.oa_status`
# accepte NULL (= la source ne s'est pas prononcée), mais au niveau
# canonique on matérialise l'absence de signal par 'unknown' (vraie
# valeur de l'enum, classée en queue d'`OA_RANK`). À utiliser comme
# fallback après `best_oa_status(...)` ou pour défaut sur
# `source_publications.oa_status` orphelin.
OA_STATUS_UNKNOWN_DEFAULT = "unknown"

# Statuts considérés comme « non-ouverts » par les règles d'absorption
# pairwise (cf. `absorb_oa_status` ci-dessous et règle SQL historique de
# `repo.merge_into` qu'elle remplace).
OA_CLOSED_STATUSES: frozenset[str] = frozenset({"closed", "unknown"})


def best_oa_status(statuses: Iterable[str | None]) -> str | None:
    """Retourne le statut OA le plus ouvert parmi `statuses`.

    Ordre décroissant : diamond > gold > hybrid > bronze > green > closed > unknown.
    Les valeurs None, vides ou inconnues sont ignorées. Retourne None
    si aucune valeur exploitable n'est fournie.
    """
    best: str | None = None
    best_rank = 0
    for s in statuses:
        if not s:
            continue
        r = OA_RANK.get(s, 0)
        if r > best_rank:
            best, best_rank = s, r
    return best


def absorb_oa_status(target: str | None, source: str | None) -> str | None:
    """Règle pairwise pour l'absorption d'une publication dans une autre.

    Distincte de `best_oa_status` (agrégation multi-sources). Quand une publication target absorbe une publication source (cas typique : fusion sur collision DOI), target conserve son statut canonique sauf dans deux cas :

    - `source == 'diamond'` : `diamond` est un trump qui gagne toujours, car peu de sources le déclarent à tort.
    - `target` est non-ouvert (`closed` ou `unknown`) ET `source` est ouvert : on s'autorise à upgrader target depuis sa zone non-informative.

    Dans tous les autres cas, target conserve son statut — y compris quand source a un statut "meilleur" au sens de `OA_RANK` (ex. target=hybrid, source=gold). Hypothèse : target.oa_status est le résultat d'un calcul canonique antérieur qu'on ne reflippe pas sur la base d'un seul signal source.

    `target` à None est traité comme une zone non-informative équivalente à `OA_CLOSED_STATUSES` (cohérent avec le défaut d'enum `'unknown'` côté schéma).
    """
    if source == "diamond":
        return "diamond"
    target_is_closed = target is None or target in OA_CLOSED_STATUSES
    source_is_open = source is not None and source not in OA_CLOSED_STATUSES
    if target_is_closed and source_is_open:
        return source
    return target


# ── Canonicalisation des titres double-encodés HTML ─────────────────
#
# OpenAlex et ScanR remontent parfois des titres avec un encodage HTML
# appliqué deux fois — par exemple "<i>Candida</i>" arrive en base sous
# la forme "&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;". On corrige au
# moment d'écrire dans `publications.title` pour que la couche canonique
# reste propre, indépendamment de la qualité du flux source.

_HTML_ENTITY_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_DOUBLE_ENCODED_RE = re.compile(r"&amp;(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _decode_html_entities_once(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name[1] in "xX" else int(name[1:])
                return chr(code)
            except (ValueError, OverflowError):
                return m.group(0)
        return _HTML_ENTITY_NAMED.get(name, m.group(0))

    return _HTML_ENTITY_RE.sub(repl, s)


def clean_publication_title(title: str | None) -> str | None:
    """Décode un titre double-encodé HTML, sinon le retourne tel quel.

    Détection : présence d'`&amp;` immédiatement suivi d'une entité connue
    (`lt`, `gt`, `amp`, `quot`, `apos`, `#NNN`, `#xHH`). Ce motif est la
    signature du double-encodage et ne se rencontre pas dans un titre
    normal (un `&amp;` isolé légitime style "Smith &amp; Jones" n'est pas
    suivi d'un nom d'entité, donc reste inchangé).

    Quand détecté, on décode deux niveaux pour retomber sur le HTML
    d'origine. Idempotent : un second appel sur le résultat ne change rien.
    """
    if not title or not _DOUBLE_ENCODED_RE.search(title):
        return title
    return _decode_html_entities_once(_decode_html_entities_once(title))
