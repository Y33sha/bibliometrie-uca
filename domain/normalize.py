"""Nettoyage des textes reçus des sources, et forme de comparaison des textes."""

import html
import re
import unicodedata

# Lettres que NFKD ne décompose pas, ramenées à leur forme sans diacritique : « Meyerhofstraße » et « Meyerhofstrasse » ont la même forme normalisée. Appliquée après lower().
_TRANSLITERATIONS = str.maketrans(
    {
        "ё": "е",  # CYRILLIC SMALL LETTER IO → IE (ё → е)
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


# Balise : `<` suivi d'une lettre ou de `/`. Le corps exclut `<` : une suite de `<` sans fermeture se parcourt en temps linéaire.
_MARKUP_RE = re.compile(r"</?([A-Za-z][^\s<>/]*)(?:[\s/][^<>]*)?>")

# Balises de mise en forme (HTML, JATS, MathML), qui s'insèrent dans un mot : `CO<sub>2</sub>`, `<i>E</i>. coli`. Comparées sans préfixe d'espace de noms (`jats:sub`, `mml:mi`).
_INLINE_TAGS = frozenset(
    {
        "sub", "sup", "i", "b", "em", "strong", "u", "span", "small", "tt", "sc", "scp",
        "italic", "bold", "underline", "monospace", "overline", "roman", "strike",
        "math", "mi", "mn", "mo", "ms", "mtext", "mrow", "msub", "msup", "msubsup",
        "mfrac", "msqrt", "mroot", "mover", "munder", "munderover", "mstyle",
        "mspace", "mpadded", "mphantom", "mfenced", "menclose", "semantics",
        "inline-formula",
    }
)  # fmt: skip


def _markup_replacement(match: re.Match[str]) -> str:
    """Rien pour une balise de mise en forme, un espace pour les autres (paragraphe, saut de ligne)."""
    return "" if match.group(1).rsplit(":", 1)[-1].lower() in _INLINE_TAGS else " "


def _strip_comments(text: str) -> str:
    """Remplace chaque commentaire `<!-- ... -->` par un espace. Une ouverture sans fermeture reste dans le texte."""
    parts: list[str] = []
    position = 0
    while (start := text.find("<!--", position)) != -1:
        end = text.find("-->", start + 4)
        if end == -1:
            break
        parts += (text[position:start], " ")
        position = end + 3
    parts.append(text[position:])
    return "".join(parts)


# Certaines sources échappent plusieurs fois une valeur (`&amp;amp;`).
_MAX_UNESCAPE_PASSES = 4


def _unescape_fully(text: str) -> str:
    """Décode les entités HTML jusqu'à stabilisation."""
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def to_plain_text(text: str | None) -> str:
    """Texte brut d'une valeur reçue d'une source : commentaires, balises et entités HTML retirés, espacement réduit à un espace simple. Une balise échappée (`&lt;p&gt;`) est retirée aussi.

    Les titres et les résumés gardent leur balisage, qui a un sens (exposants, MathML). Ils passent par ici seulement pour un export en tableur.
    """
    if not text:
        return ""
    without_comments = _strip_comments(_unescape_fully(text))
    return " ".join(strip_markup(without_comments).split())


# Le retrait d'une balise imbriquée (`<ab<aa>a>`) en reconstitue une autre. Chaque passe coûte un parcours du texte.
_MAX_MARKUP_PASSES = 8


def strip_markup(text: str) -> str:
    """Texte sans balises HTML ni MathML. Une balise de mise en forme disparaît sans couper le mot (`CO<sub>2</sub>` → `CO2`), les autres deviennent un espace. Les indices de Miller (`<111>`) et les inégalités (`2.96<yCMS<3.53`) restent."""
    for _ in range(_MAX_MARKUP_PASSES):
        stripped = _MARKUP_RE.sub(_markup_replacement, text)
        if stripped == text:
            break
        text = stripped
    return text


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_tex_formula(line: str) -> bool:
    """La ligne est une formule LaTeX `$$…$$` seule."""
    stripped = line.strip()
    return len(stripped) > 4 and stripped.startswith("$$") and stripped.endswith("$$")


def _flattened_mathml(line: str, depth: int) -> bool:
    """Ligne vide, ou symbole isolé plus indenté que la formule."""
    stripped = line.strip()
    return not stripped or (len(stripped.split()) == 1 and _indent(line) > depth)


def drop_flattened_mathml(title: str) -> str:
    """Titre sans la version MathML de ses formules, espacement réduit à un espace simple.

    Un éditeur dépose chaque formule d'un titre en deux versions : LaTeX (`$$…$$`) et MathML. Crossref rend le titre avec l'indentation du XML déposé et sans les balises MathML : la formule LaTeX occupe une ligne, et chaque symbole MathML une ligne plus indentée qu'elle, avant ou après. ScanR recopie ce titre. Ces lignes de symboles isolés sont retirées. L'interface affiche la formule LaTeX.

    Un titre déjà mis sur une ligne (OpenAlex) ne garde aucun repère : seul son espacement est réduit.
    """
    lines = title.split("\n")
    dropped: set[int] = set()
    for i, line in enumerate(lines):
        if not _is_tex_formula(line):
            continue
        # Une formule en début de ligne n'a pas d'indentation : la ligne suivante a celle du bloc.
        depth = _indent(line) or (_indent(lines[i + 1]) if i + 1 < len(lines) else 0)
        for step in (1, -1):
            j = i + step
            while (
                0 <= j < len(lines)
                and not _is_tex_formula(lines[j])
                and _flattened_mathml(lines[j], depth)
            ):
                dropped.add(j)
                j += step
    return " ".join(" ".join(line for k, line in enumerate(lines) if k not in dropped).split())


# Formule MathML. Son corps exclut une autre ouverture. La fin du texte ferme une formule : OpenAlex tronque des résumés en pleine formule.
_MATHML_FORMULA = r"<mml:math\b(?:(?!<mml:math\b).)*?(?:</mml:math>|\Z)"
# Formules LaTeX `$$…$$` suivies de leurs versions MathML, sans texte entre elles.
_TEX_THEN_MATHML_RE = re.compile(rf"(\$\$[^$]+\$\$)(?:\s*{_MATHML_FORMULA})+", re.DOTALL)
_MATHML_FORMULA_RE = re.compile(_MATHML_FORMULA, re.DOTALL)
_TEX_ANNOTATION_RE = re.compile(
    r'<mml:annotation\b[^>]*encoding="application/x-tex"[^>]*>(.*?)</mml:annotation>', re.DOTALL
)


def _annotation_tex(match: re.Match[str]) -> str:
    """Version LaTeX `$$…$$` de l'annotation de la formule, la formule à défaut."""
    annotation = _TEX_ANNOTATION_RE.search(match.group())
    return f"$${annotation.group(1).strip()}$$" if annotation else match.group()


def drop_duplicate_mathml(abstract: str | None) -> str | None:
    """Résumé où chaque formule a une seule version, LaTeX quand l'éditeur en dépose une.

    Un éditeur dépose une formule en deux versions de deux manières. Soit la version LaTeX `$$…$$` précède la formule MathML. Plusieurs formules LaTeX consécutives précèdent alors leurs versions MathML consécutives. Soit la formule MathML contient sa version LaTeX dans une annotation `<mml:annotation encoding="application/x-tex">`. La formule MathML est retirée, et la version LaTeX prend sa place. Une formule MathML seule reste.
    """
    if not abstract or "<mml:math" not in abstract:
        return abstract
    return _MATHML_FORMULA_RE.sub(_annotation_tex, _TEX_THEN_MATHML_RE.sub(r"\1", abstract))


_ABSTRACT_LABELS = (
    "Abstract",
    "Résumé",
    "Resume",
    "Summary",
    "Resumen",
    "Zusammenfassung",
    "Riassunto",
)
_ABSTRACT_LABEL = "|".join(
    form for label in _ABSTRACT_LABELS for form in (label, label.lower(), label.upper())
)
# Intitulé seul dans une balise de titre, suivi d'une ponctuation, ou suivi d'une majuscule, d'un chiffre ou d'une formule.
_ABSTRACT_LABEL_RE = re.compile(
    rf"^\s*(?:<(?:jats:)?title>\s*(?:{_ABSTRACT_LABEL})\s*[.:]?\s*</(?:jats:)?title>\s*"
    rf"|(?:{_ABSTRACT_LABEL})(?:\s*[.:：–—-]\s*|\s+(?=[A-ZÀ-ÖØ-Þ0-9(\[<$«\"“])))"
)


def strip_abstract_label(abstract: str | None) -> str | None:
    """Résumé sans l'intitulé qui le précède chez certaines sources (« Abstract », « Résumé : », `<title>Abstract</title>`).

    Un mot suivi d'une minuscule ouvre une phrase (« Summary statistics are… ») : il reste.
    """
    if not abstract:
        return abstract
    return _ABSTRACT_LABEL_RE.sub("", abstract, count=1) or None


_GREEK_LETTERS = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho"
    " sigma tau upsilon phi chi psi omega"
).split()
_GREEK_COMMANDS: dict[str, str] = {
    **{name: chr(0x03B1 + i + (i > 16)) for i, name in enumerate(_GREEK_LETTERS)},
    **{name.capitalize(): chr(0x0391 + i + (i > 16)) for i, name in enumerate(_GREEK_LETTERS)},
    "varepsilon": "ε",
    "vartheta": "θ",
    "varpi": "π",
    "varrho": "ρ",
    "varsigma": "ς",
    "varphi": "φ",
    "ell": "ℓ",
}

# Accent LaTeX sur une lettre : `\'e`, `\'{e}`, `\c{c}`, `\v c`. Groupe 1 : la commande d'accent ; groupe 2 ou 3 : la lettre. Les commandes faites d'une lettre (`\c`, `\v`) sont suivies d'une accolade ou d'une espace.
# Une source qui met un nom en majuscules met aussi la commande (`Gon\C Calo`).
_LATEX_ACCENT_RE = re.compile(
    r"\\([`'^\"~=.]|[cvuHkrCVUKR](?=[\s{]))(?:\{\s*([A-Za-zı])\s*\}|\s*([A-Za-zı]))"
)
_LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
# Diacritique combinant de chaque commande d'accent.
_LATEX_ACCENTS = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
    ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328",
    "r": "\u030a", "U": "\u0306", "V": "\u030c", "C": "\u0327", "K": "\u0328", "R": "\u030a",
}  # fmt: skip
# Lettres LaTeX sans équivalent ASCII : `\o` → ø, `\ss` → ß. `\i` est le i sans point, qui reçoit un accent (`\'{\i}`).
_LATEX_LETTERS = {
    "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "ss": "ß", "Ss": "ß",
    "SS": "ß", "o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "i": "ı",
}  # fmt: skip
# `\ss` se reconnaît même collé au reste du mot (`Ge\ssner`) : aucune autre commande ne commence par ss.
_LATEX_LETTER_RE = re.compile(r"\\(ss|Ss|SS|(?:aa|AA|ae|AE|oe|OE|[oOlLi])(?![A-Za-z]))")


def strip_latex(text: str) -> str:
    """Retire les commandes LaTeX d'un texte. Une lettre accentuée (`\\'e`) garde sa lettre, une lettre grecque (`\\psi`) devient le caractère grec, toute autre commande (`\\rm`, `\\sqrt`, `\\bar`) disparaît. Les arguments restent ; les délimiteurs (`$ { } ^ _`) sont laissés à l'appelant."""
    if "\\" not in text:
        return text
    text = _LATEX_ACCENT_RE.sub(lambda m: m.group(2) or m.group(3), text)
    return _LATEX_COMMAND_RE.sub(lambda m: _GREEK_COMMANDS.get(m.group(1), " "), text)


def decode_latex_accents(text: str) -> str:
    """Texte dont les accents et les lettres LaTeX deviennent leur caractère, sans les accolades de groupement : `Fr\\'ed\\'eric` → Frédéric, `Besan\\c{c}on` → Besançon, `J{\\o}rgensen` → Jørgensen."""
    if "\\" not in text:
        return text
    text = _LATEX_LETTER_RE.sub(lambda m: _LATEX_LETTERS[m.group(1)], text)

    def accent(m: re.Match[str]) -> str:
        letter = m.group(2) or m.group(3)
        return ("i" if letter == "ı" else letter) + _LATEX_ACCENTS[m.group(1)]

    text = _LATEX_ACCENT_RE.sub(accent, text)
    return unicodedata.normalize("NFC", text.replace("{", "").replace("}", ""))


def _byte_readings(byte: int) -> str:
    """Caractères que Latin-1 et Windows-1252 lisent pour `byte`. Ils diffèrent seulement de 0x80 à 0x9F, où Latin-1 lit un caractère de contrôle."""
    try:
        return chr(byte) + bytes([byte]).decode("cp1252")
    except UnicodeDecodeError:
        return chr(byte)


# Octets 0x80 à 0xFF, indexés par leurs lectures Latin-1 et Windows-1252.
_BYTES = {c: b for b in range(0x80, 0x100) for c in _byte_readings(b)}
_CONTINUATION = "".join(_byte_readings(b) for b in range(0x80, 0xC0))
# Caractère UTF-8 lu comme du Latin-1 ou du Windows-1252 : un octet de tête, puis autant d'octets de continuation qu'il en annonce.
_UTF8_AS_CP1252 = f"[Â-ß][{_CONTINUATION}]|[à-ï][{_CONTINUATION}]{{2}}|[ð-ô][{_CONTINUATION}]{{3}}"
# Texte Windows-1252 lu comme du GBK : une lettre accentuée et la lettre ASCII qui la suit forment un idéogramme, collé à une lettre latine.
_CP1252_AS_GBK = "(?<=[A-Za-z])[一-鿿]+"
# Expression des deux défauts d'encodage que `repair_encoding` répare, valable aussi pour PostgreSQL.
ENCODING_ERROR_PATTERN = f"{_UTF8_AS_CP1252}|{_CP1252_AS_GBK}"
_UTF8_AS_CP1252_RE = re.compile(_UTF8_AS_CP1252)
_CP1252_AS_GBK_RE = re.compile(_CP1252_AS_GBK)


def _from_utf8(m: re.Match[str]) -> str:
    try:
        return bytes(_BYTES[c] for c in m.group()).decode("utf-8")
    except UnicodeDecodeError:
        return m.group()


def _from_gbk(m: re.Match[str]) -> str:
    try:
        pairs = [c.encode("gbk") for c in m.group()]
    except UnicodeEncodeError:
        return m.group()
    if not all(
        len(p) == 2 and p[0] >= 0x80 and chr(p[1]).isascii() and chr(p[1]).isalpha() for p in pairs
    ):
        return m.group()
    try:
        return b"".join(pairs).decode("cp1252")
    except UnicodeDecodeError:
        return m.group()


def repair_encoding(text: str) -> str:
    """Texte dont l'encodage erroné est réparé : UTF-8 lu comme du Latin-1 ou du Windows-1252 (« TÃ©lesphore » → Télesphore), Windows-1252 lu comme du GBK (« Fran鏾is » → François)."""
    if text.isascii():
        return text
    return _CP1252_AS_GBK_RE.sub(_from_gbk, _UTF8_AS_CP1252_RE.sub(_from_utf8, text))


def sanitize_raw_text(text: str) -> str:
    """Texte brut sans balisage, sans entités HTML ni caractères invisibles, espacement réduit à un espace simple. Casse, accents et ponctuation restent : le texte sert à l'affichage et à la recherche."""
    if not text:
        return ""
    text = to_plain_text(text)
    # `to_plain_text` réduit déjà l'espacement : un texte imprimable n'a plus rien à retirer.
    if text.isprintable():
        return text
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
    """Valeur d'un champ importé, nettoyée par `sanitize_raw_text` ; `None` si elle est vide."""
    return sanitize_raw_text(text or "") or None


_ASCII_SEPARATORS_RE = re.compile(r"[^a-z0-9]+")


def _drops_marks(base: str) -> bool:
    """Vrai quand les diacritiques qui suivent `base` se retirent : derrière une lettre latine ou grecque, ou derrière un caractère qui n'est pas une lettre. Ailleurs, ils distinguent des lettres (й, が)."""
    return not base.isalpha() or unicodedata.name(base, "").startswith(("LATIN", "GREEK"))


def _is_word_character(ch: str) -> bool:
    """Lettre ou chiffre, hors lettres modificatives d'espacement (U+02B0–U+02FF) : apostrophe `ʼ`, okina `ʻ`, caron `ˇ` isolé d'une extraction PDF (« Maˇsek »)."""
    return ch.isalnum() and not "ʰ" <= ch <= "˿"


def normalize_text(text: str) -> str:
    """Forme de comparaison d'un texte, pour le dédoublonnage et le rapprochement : sans balises ni commandes LaTeX, en minuscules, ligatures et exposants décomposés (ﬁ → fi, ² → 2), sans diacritiques sur les lettres latines et grecques. Tout caractère autre qu'une lettre ou un chiffre devient un espace."""
    if not text:
        return ""
    text = strip_latex(strip_markup(text)).lower()
    if text.isascii():
        return " ".join(_ASCII_SEPARATORS_RE.sub(" ", text).split())
    # La décomposition produit des majuscules (№ → No) : seconde mise en minuscules.
    text = unicodedata.normalize("NFKD", text.translate(_TRANSLITERATIONS)).lower()
    out: list[str] = []
    base = " "
    for ch in text:
        if unicodedata.category(ch).startswith("M"):
            if not _drops_marks(base):
                out.append(ch)
            continue
        base = ch
        out.append(ch if _is_word_character(ch) else " ")
    return " ".join(unicodedata.normalize("NFC", "".join(out)).split())


_DIGITS_RE = re.compile(r"\d+")
# Parenthèses ou crochets que le retrait des chiffres a vidés : « (1278759) », « (1960-2020) ».
_EMPTY_BRACKETS_RE = re.compile(r"[(\[][^\w()\[\]]*[)\]]")
# Mot fait de ponctuation seule : le tiret de « Wolff, Charlotta 1976- », isolé par le retrait des chiffres.
_PUNCTUATION_ONLY_RE = re.compile(r"[^\w\s'’]+")
# Séparateurs en fin de nom : la virgule de « D'Andrea, Carlos, 1973- ». Le point d'une initiale reste.
_TRAILING_SEPARATORS = ",;:-–—/"


def clean_raw_author_name(raw: str) -> str:
    """Nom d'auteur brut sans balisage ni chiffres, accents LaTeX et encodage réparés. La ponctuation que le retrait des chiffres isole disparaît aussi.

    Les chiffres d'un nom sont une année de naissance (« Candoni, Jean-François 1964- »), un identifiant de source ou un renvoi d'affiliation (« Ibrahim1 »). Un nom fait seulement de chiffres et de ponctuation reste tel quel.
    """
    if not raw:
        return raw
    text = decode_latex_accents(repair_encoding(to_plain_text(raw)))
    # Accolades de groupement LaTeX restées sans commande : « Geß{}ner ».
    text = text.replace("{", "").replace("}", "")
    cleaned = " ".join(_EMPTY_BRACKETS_RE.sub(" ", _DIGITS_RE.sub("", text)).split())
    # Parenthèse que le retrait des chiffres a détachée de son contenu : « (EA 999) » → « (EA) ».
    cleaned = cleaned.replace(" )", ")").replace(" ]", "]")
    words = [word for word in cleaned.split(" ") if not _PUNCTUATION_ONLY_RE.fullmatch(word)]
    cleaned = " ".join(words).rstrip(_TRAILING_SEPARATORS).strip()
    return cleaned or " ".join(text.split())
