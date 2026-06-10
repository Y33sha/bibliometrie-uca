"""Règles pures de **distinction** des publications.

Inverse des règles de déduplication (`deduplication.py` / `metadata_deduplication_rules.py`) : au lieu de reconnaître que deux publications sont la même, on reconnaît que deux publications qui **partagent une clé de fusion** (DOI, hal_id, …) sont en réalité des **documents distincts** qui ne doivent jamais fusionner.

Le résultat alimente la table `distinct_publications` (paire ordonnée `pub_id_a < pub_id_b`), consultée comme garde par les passes de fusion (et par les pages doublons admin).

Chaque cas énonce sa règle métier dans le docstring de son membre d'enum — source unique de l'énoncé. La détection est **pure** : pas d'I/O, pas d'effet de bord (ni `clear` de DOI, ni fusion). Le caller (passe applicative) fournit les paires partageant une clé et persiste le marquage.

Distinct de la règle générale « deux DOI non-nuls différents ⇒ pas de fusion », qui est une garde dans `merge_publications` et ne transite pas par cette table (elle marquerait un nombre arbitraire de paires).
"""

from enum import StrEnum

# doc_types **canoniques** (`publications.doc_type`, déjà mappé via
# `map_doc_type` ; pas de variante brute « book-chapter »/« couv »…). Seule la
# famille thèse regroupe plusieurs valeurs ; `book`/`book_chapter`/`article`
# sont comparés en clair dans `detect_distinct_case`.
_THESIS_DOC_TYPES: frozenset[str] = frozenset({"thesis", "ongoing_thesis", "memoir"})


class DistinctPublicationCase(StrEnum):
    """Cas explicites de publications à marquer distinctes (jamais fusionnables).

    Chaque membre énonce sa règle dans le commentaire qui le précède. La
    détection vit dans `detect_distinct_case` (pure) ; l'application sur les
    paires candidates et l'écriture dans `distinct_publications` vivent côté
    application.
    """

    # Ouvrage et chapitre partageant le DOI : le DOI est celui de l'ouvrage
    # (`book`), le chapitre (`book_chapter`) ne fait que le porter par erreur.
    # Documents distincts.
    OUVRAGE_VS_CHAPITRE = "ouvrage_vs_chapitre"

    # Deux chapitres (`book_chapter`) partageant un DOI mais de titres
    # normalisés différents : DOI partagé erroné, deux chapitres distincts.
    CHAPITRES_TITRES_DIFFERENTS = "chapitres_titres_differents"

    # Une thèse/mémoire (`thesis`/`ongoing_thesis`/`memoir`) et un article
    # (`article`) partageant une clé : documents distincts (typiquement une
    # thèse d'exercice déposée + l'article publié, regroupés à tort par une
    # source). Cf. chantier fusions abusives.
    THESE_VS_ARTICLE = "these_vs_article"


def detect_distinct_case(
    *,
    doc_type_a: str | None,
    title_normalized_a: str | None,
    doc_type_b: str | None,
    title_normalized_b: str | None,
) -> DistinctPublicationCase | None:
    """Pour une paire de publications **qui partagent une clé de fusion**,
    renvoie le cas de distinction si l'une des règles connues s'applique, sinon
    `None` (la paire reste candidate à la fusion).

    Pur, symétrique (l'ordre a/b n'importe pas), sans effet de bord.
    """
    types = {doc_type_a or "", doc_type_b or ""}

    # Ouvrage et chapitre partageant le DOI : il appartient à l'ouvrage.
    if types == {"book", "book_chapter"}:
        return DistinctPublicationCase.OUVRAGE_VS_CHAPITRE

    # Deux chapitres au DOI partagé mais titres différents : DOI erroné.
    if types == {"book_chapter"} and (title_normalized_a or "") != (title_normalized_b or ""):
        return DistinctPublicationCase.CHAPITRES_TITRES_DIFFERENTS

    # Thèse/mémoire et article : documents distincts.
    if types & _THESIS_DOC_TYPES and "article" in types:
        return DistinctPublicationCase.THESE_VS_ARTICLE

    return None
