"""Fonctions de normalisation centralisées.

Toutes les normalisations textuelles du projet passent par ce module afin d'éviter la duplication et les incohérences.

La normalisation Python est la référence ; la fonction SQL normalize_name_form() est alignée dessus (filet de non-régression : tests/integration/test_normalize_alignment_python_sql.py). Pipeline : minuscules → lettres latines autonomes → NFKD → retrait des diacritiques → tout sauf [a-z0-9] → espaces → collapse.
"""

import html
import re
import unicodedata

# Lettres latines autonomes que NFKD ne décompose pas (ce ne sont pas des
# base+diacritique mais des lettres à part entière) alors que PostgreSQL
# unaccent les translittère. Sans cette table elles seraient supprimées par
# le passage [^a-z0-9] et colleraient leurs voisins ("Meyerhofstrasse"
# perdrait son ss). Les valeurs reproduisent unaccent. Appliquée après
# lower(), donc les majuscules sont déjà repliées sur leur minuscule.
_LATIN_LETTERS = str.maketrans(
    {
        "\u00df": "ss",  # LATIN SMALL LETTER SHARP S
        "\u00f8": "o",  # LATIN SMALL LETTER O WITH STROKE
        "\u0142": "l",  # LATIN SMALL LETTER L WITH STROKE
        "\u0131": "i",  # LATIN SMALL LETTER DOTLESS I
        "\u0111": "d",  # LATIN SMALL LETTER D WITH STROKE
        "\u00f0": "d",  # LATIN SMALL LETTER ETH
        "\u00fe": "th",  # LATIN SMALL LETTER THORN
        "\u0127": "h",  # LATIN SMALL LETTER H WITH STROKE
        "\u014b": "n",  # LATIN SMALL LETTER ENG
        "\u0167": "t",  # LATIN SMALL LETTER T WITH STROKE
        "\u0138": "k",  # LATIN SMALL LETTER KRA
        "\u017f": "s",  # LATIN SMALL LETTER LONG S
        "\u0153": "oe",  # LATIN SMALL LIGATURE OE
        "\u00e6": "ae",  # LATIN SMALL LIGATURE AE
    }
)


_MARKUP_RE = re.compile(r"</?[A-Za-z][^<>]*>")


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Nombre de passes de décodage des entités. Chaque passe raccourcit strictement la chaîne, donc
# la stabilisation vient d'elle-même ; la borne évite d'en dépendre.
_MAX_UNESCAPE_PASSES = 4


def _unescape_fully(text: str) -> str:
    """Décode les entités HTML jusqu'à ce que la chaîne ne bouge plus, au plus `_MAX_UNESCAPE_PASSES` fois."""
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def to_plain_text(text: str | None) -> str:
    """Texte brut d'une valeur reçue d'une source : commentaires, balises et entités HTML retirés, espacement réduit à un espace simple.

    Les sources déposent du balisage dans des champs dont il ne porte pas le sens — une adresse d'affiliation enveloppée dans un paragraphe, un libellé de sujet en italique, un nom d'auteur portant une entité. Ce balisage n'a aucun consommateur : l'interface affiche ces champs en texte, l'export les écrit en texte, et le rapprochement les normalise. Le retirer à l'entrée évite de le retirer dans chacun d'eux.

    Les entités sont décodées avant le retrait des balises, si bien qu'une balise échappée (`&lt;p&gt;`) subit le même sort que la balise elle-même. Le décodage se répète jusqu'à stabilisation : certaines sources ré-échappent une valeur déjà échappée (`&amp;amp;`), qu'une passe unique laisserait à moitié décodée. Le retrait suit `strip_markup`, qui épargne les indices de Miller.

    À ne pas appliquer aux titres ni aux résumés de publication, dont le balisage porte du sens — exposants, indices, MathML — et que l'interface rend. Leur mise à plat pour un tableur, elle, passe bien par ici.
    """
    if not text:
        return ""
    without_comments = _COMMENT_RE.sub(" ", _unescape_fully(text))
    return " ".join(strip_markup(without_comments).split())


def strip_markup(text: str) -> str:
    """Retire les balises HTML/MathML `<...>` (remplacées par un espace).

    Le premier caractère doit être une lettre (ou `/`) pour ne pas avaler les indices de Miller `<111>` / `< 110 >` (cristallographie), qui sont du contenu, pas du markup (audit titres bruts : seuls cas non-balise observés).

    Le corps d'une balise exclut `<` : une inégalité de la notation scientifique (`2.96<yCMS<3.53`) s'arrête ainsi au signe suivant, et une suite de `<` sans fermeture se parcourt linéairement.

    Le retrait se répète jusqu'à ce que le texte ne bouge plus : une balise imbriquée dans une autre (`<ab<aa>a>`) en reconstitue une au retrait de la première, qu'une passe unique laisserait passer. Chaque passe qui change quelque chose consomme au moins un `<`, ce qui borne leur nombre par le compte de `<` du texte reçu.

    Réutilisé par l'export CSV (titre brut) et par `normalize_text` (dédup).
    """
    for _ in range(text.count("<")):
        stripped = _MARKUP_RE.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    return text


def sanitize_raw_text(text: str) -> str:
    """Assainit un texte brut de son bruit invisible, sans le dénaturer.

    Contrairement à `normalize_text` (qui produit une clé de comparaison repliée), préserve casse, accents et ponctuation : sert au texte brut affiché et recherché (`addresses.raw_text`), pas à une clé de matching.

    - tout caractère d'espacement Unicode (NBSP, fine insécable, tabulation…) → espace simple
    - suppression des caractères de format/contrôle invisibles (zero-width, BOM, trait d'union conditionnel, marques directionnelles, contrôles C0/C1)
    - collapse des espaces multiples + strip

    Le balisage et les entités HTML sont retirés en amont (`to_plain_text`) : une adresse d'affiliation enveloppée dans un paragraphe ou portant `&eacute;` converge sur le même texte que la même adresse déposée en clair.

    Remplace `str.strip()` au point d'insertion des adresses : deux textes ne différant que par un espace insécable convergent ainsi sur la même `raw_text`.
    """
    if not text:
        return ""
    text = to_plain_text(text)
    out: list[str] = []
    for ch in text:
        if ch.isspace():
            out.append(" ")
        elif unicodedata.category(ch) in ("Cf", "Cc", "Cs", "Co"):
            continue
        else:
            out.append(ch)
    return re.sub(r" +", " ", "".join(out)).strip()


def sanitize_optional_text(text: str | None) -> str | None:
    """Valeur d'un champ importé, mise à plat par `sanitize_raw_text`, ou `None` quand elle ne porte rien.

    Point d'entrée des imports de fichiers : les colonnes d'un tableur ou d'un export tiers arrivent avec le même bruit que les champs moissonnés — balisage collé par un copier-coller, entités HTML, espaces insécables, caractères de format invisibles — et alimentent les mêmes rapprochements (nom d'éditeur, titre de revue, nom de personne). Les traiter comme les champs moissonnés fait converger les deux voies d'entrée sur la même forme.

    Une cellule vide, ou vide une fois mise à plat, rend `None` plutôt qu'une chaîne vide : les colonnes concernées sont nullables et une chaîne vide y ferait un second cas d'absence.
    """
    return sanitize_raw_text(text or "") or None


def normalize_text(text: str) -> str:
    """Normalise un texte pour comparaison / dédoublonnage / matching.

    Pipeline :
      1. retirer les balises (MathML/HTML) `<...>` entièrement
      2. minuscules + strip
      3. translittérer les lettres latines autonomes (ß, ø, ł...)
      4. NFKD (décompose les caractères accentués et de compatibilité)
      5. retirer les seules combining marks (diacritiques)
      6. tout sauf [a-z0-9] → espaces (les symboles restants n'avalent donc pas leurs voisins)
      7. collapse espaces multiples
    """
    if not text:
        return ""
    # Retrait des balises avant tout, sinon `mml`/`i`/`sub`… subsisteraient comme texte après l'étape [^a-z0-9] et pollueraient le dédoublonnage.
    text = strip_markup(text)
    text = text.lower().strip()
    text = text.translate(_LATIN_LETTERS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def normalize_label(label: str) -> str:
    """Assainit un libellé de sujet avant insertion : trim + collapse des espaces internes.

    Préserve casse et accents ; la déduplication se fait en SQL via `lower(label)` (index unique), et `subjects.label` garde la forme du premier insert. Le balisage qu'une source dépose autour d'un nom d'espèce (`<italic>`) est retiré : un libellé s'affiche en texte.
    """
    return to_plain_text(label)


# Alias — normalize_name est identique à normalize_text.
# Les deux noms sont conservés pour la lisibilité du code appelant.
normalize_name = normalize_text

# Équivalent Python de la fonction SQL normalize_name_form()
normalize_name_form = normalize_text


_PAREN_NUMERIC_ID_RE = re.compile(r"\s*\(\d+\)")


def clean_raw_author_name(raw: str) -> str:
    """Retire d'un nom d'auteur brut les identifiants numériques entre parenthèses.

    Certaines signatures portent un identifiant de source recopié dans le nom lui-même (« Emmanuel Moreau (1278759) »). Un groupe purement numérique entre parenthèses n'a pas de sens dans un nom : laissé en place, il contamine le nom affiché, le nom normalisé (qui sert de clé d'identité au rapprochement cross-source) et les formes de nom dérivées. Ce nettoyage neutralise le parasite à l'entrée, quelle que soit la source.

    Le balisage et les entités qu'une source dépose dans une signature sont retirés du même geste : un nom d'auteur s'affiche en texte.
    """
    if not raw:
        return raw
    return re.sub(r" +", " ", _PAREN_NUMERIC_ID_RE.sub(" ", to_plain_text(raw))).strip()
