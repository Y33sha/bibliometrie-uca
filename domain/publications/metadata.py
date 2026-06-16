"""Règles métier sur les métadonnées de publication — domain services
purs sans état d'instance.

Catch-all pour les règles qui touchent aux métadonnées d'une
publication (oa_status, titre canonique, …) et n'ont pas de meilleure
cible. À mesure qu'un type d'opération gagne en volume, il peut sortir
dans son propre module.
"""

import re
from collections.abc import Iterable

from domain.normalize import normalize_text

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

# Statuts OA « stables » : une fois vérifiés par Unpaywall ils ne changent plus
# (un accès gold/diamond/hybrid reste ouvert dans le temps). La phase `oa_status`
# ne les re-interroge donc **jamais** une fois vérifiés. Les autres
# (`closed`/`green`/`bronze`/`unknown`) peuvent évoluer et sont re-vérifiés quand
# périmés (staleness). Source unique pour le filtre SQL de `fetch_publications_with_doi`.
STABLE_OA_STATUSES: frozenset[str] = frozenset({"gold", "diamond", "hybrid"})

STABLE_OA_STATUSES_SQL: str = "(" + ", ".join(f"'{s}'" for s in sorted(STABLE_OA_STATUSES)) + ")"
"""Forme SQL ``('diamond', 'gold', 'hybrid')`` pour la clause ``NOT IN``."""


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


def has_minimal_publication_metadata(title: str | None, pub_year: int | None) -> bool:
    """Indique si une publication candidate a les métadonnées minimales nécessaires à sa création.

    Invariant posé à l'insertion : titre non vide ET année renseignée. Une publication sans ces deux champs n'a pas de valeur métier (pas de référence biblio consultable, pas d'année pour les statistiques) et est filtrée par les normalizers en amont de `find_or_create`.

    Une `pub_year` à 0 est considérée comme absente (cas pathologique : `bool(0) is False`).
    """
    return bool(title) and bool(pub_year)


_WHITESPACE_RE = re.compile(r"\s+")


def clean_publication_title(title: str | None) -> str | None:
    """Nettoie un titre pour la persistance et l'affichage.

    - Décode un titre double-encodé HTML (signature `&amp;` immédiatement suivi
      d'une entité connue : `lt`, `gt`, `amp`, `quot`, `apos`, `#NNN`, `#xHH` ;
      un `&amp;` isolé légitime style "Smith &amp; Jones" reste inchangé). Deux
      niveaux de décodage pour retomber sur le HTML d'origine.
    - Collapse le whitespace parasite (newlines / tabs / espaces multiples → un
      seul espace, trim) : fréquent quand le markup source (MathML/HTML) est
      indenté dans le titre.

    Conserve les balises HTML (rendues à l'affichage). Idempotent.
    """
    if not title:
        return title
    if _DOUBLE_ENCODED_RE.search(title):
        title = _decode_html_entities_once(_decode_html_entities_once(title))
    return _WHITESPACE_RE.sub(" ", title).strip()


def normalized_title(title: str | None) -> str:
    """Forme normalisée d'un titre pour le blocking / la dédup / le matching : nettoyage HTML
    (`clean_publication_title`) puis `normalize_text`. Déterministe et idempotent — c'est la
    valeur matérialisée dans `source_publications.title_normalized`, identique à ce que le
    matcher calcule à la volée."""
    return normalize_text(clean_publication_title(title) or "")
