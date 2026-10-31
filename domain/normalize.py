"""Nettoyage des textes reçus des sources, et forme de comparaison des textes."""

import html
import re
import unicodedata

# Lettres non décomposées par NFKD, ramenées à leur forme sans diacritique : « Meyerhofstraße » et « Meyerhofstrasse » ont la même forme normalisée. Appliquée après lower().
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
    """Renvoie une chaîne vide pour une balise de mise en forme, un espace pour les autres (paragraphe, saut de ligne)."""
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


def unescape_html(text: str) -> str:
    """Décode les entités HTML jusqu'à stabilisation."""
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def to_plain_text(text: str | None) -> str:
    """Renvoie le texte brut d'une valeur reçue d'une source : commentaires, balises et entités HTML retirés, espacement réduit à un espace simple. Une balise échappée (`&lt;p&gt;`) est retirée aussi.

    Les titres et les résumés gardent leur balisage, qui a un sens (exposants, MathML). Ils passent par ici seulement pour un export en tableur.
    """
    if not text:
        return ""
    without_comments = _strip_comments(unescape_html(text))
    return " ".join(strip_markup(without_comments).split())


# Le retrait d'une balise imbriquée (`<ab<aa>a>`) en reconstitue une autre. Chaque passe coûte un parcours du texte.
_MAX_MARKUP_PASSES = 8


def strip_markup(text: str) -> str:
    """Retire les balises HTML et MathML. Une balise de mise en forme disparaît sans couper le mot (`CO<sub>2</sub>` → `CO2`), les autres deviennent un espace. Les indices de Miller (`<111>`) et les inégalités (`2.96<yCMS<3.53`) restent."""
    for _ in range(_MAX_MARKUP_PASSES):
        stripped = _MARKUP_RE.sub(_markup_replacement, text)
        if stripped == text:
            break
        text = stripped
    return text


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_tex_formula(line: str) -> bool:
    """Vrai si la ligne est une formule LaTeX `$$…$$` seule."""
    stripped = line.strip()
    return len(stripped) > 4 and stripped.startswith("$$") and stripped.endswith("$$")


def _flattened_mathml(line: str, depth: int) -> bool:
    """Vrai pour une ligne vide, ou un symbole isolé plus indenté que la formule."""
    stripped = line.strip()
    return not stripped or (len(stripped.split()) == 1 and _indent(line) > depth)


def drop_flattened_mathml(title: str) -> str:
    """Retire du titre la version MathML de ses formules, et réduit l'espacement à un espace simple.

    Un éditeur dépose chaque formule d'un titre en deux versions : LaTeX (`$$…$$`) et MathML. Crossref renvoie le titre avec l'indentation du XML déposé et sans les balises MathML. La formule LaTeX occupe une ligne. Chaque symbole MathML occupe une ligne d'indentation supérieure, avant ou après. ScanR recopie ce titre. Ces lignes de symboles isolés sont retirées. L'interface affiche la formule LaTeX.

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
    """Renvoie la version LaTeX `$$…$$` de l'annotation de la formule, la formule à défaut."""
    annotation = _TEX_ANNOTATION_RE.search(match.group())
    return f"$${annotation.group(1).strip()}$$" if annotation else match.group()


def drop_duplicate_mathml(abstract: str | None) -> str | None:
    """Garde une seule version de chaque formule d'un résumé : la version LaTeX, si l'éditeur la dépose.

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


# Intitulés empilés en tête d'un même résumé : « Abstract Summary ».
_MAX_ABSTRACT_LABELS = 3


def strip_abstract_label(abstract: str | None) -> str | None:
    """Retire les intitulés placés en tête du résumé par certaines sources (« Abstract », « Résumé : », `<title>Abstract</title>`, « Abstract Summary »).

    Un mot suivi d'une minuscule ouvre une phrase (« Summary statistics are… ») : il reste.
    """
    if not abstract:
        return abstract
    for _ in range(_MAX_ABSTRACT_LABELS):
        stripped = _ABSTRACT_LABEL_RE.sub("", abstract, count=1)
        if stripped == abstract:
            break
        abstract = stripped
    return abstract or None


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


def _accented(m: re.Match[str]) -> str:
    """Renvoie la lettre accentuée d'une correspondance de `_LATEX_ACCENT_RE`, précomposée si Unicode a le caractère."""
    letter = m.group(2) or m.group(3)
    return unicodedata.normalize(
        "NFC", ("i" if letter == "ı" else letter) + _LATEX_ACCENTS[m.group(1)]
    )


def decode_latex_accents(text: str) -> str:
    """Convertit les accents et les lettres LaTeX en caractères, et retire les accolades de groupement : `Fr\\'ed\\'eric` → Frédéric, `Besan\\c{c}on` → Besançon, `J{\\o}rgensen` → Jørgensen."""
    if "\\" not in text:
        return text
    text = _LATEX_LETTER_RE.sub(lambda m: _LATEX_LETTERS[m.group(1)], text)
    text = _LATEX_ACCENT_RE.sub(_accented, text)
    return unicodedata.normalize("NFC", text.replace("{", "").replace("}", ""))


# Formule délimitée par des dollars : $$...$$ ou $...$.
_MATH_SEGMENT_RE = re.compile(r"\$\$[\s\S]+?\$\$|\$[^$]+?\$")
# Barre oblique doublée devant une commande d'accent, laissée par un texte échappé deux fois dont une autre commande a gardé sa barre simple.
_DOUBLED_ACCENT_BACKSLASH_RE = re.compile(r"\\\\(?=[`'^\"~=.]|[cvuHkrCVUKR]\{)")
# Paire de guillemets échappés (`the \"cold\" case`) : les `\"` du texte sont des guillemets, non des trémas.
_ESCAPED_QUOTE_PAIR_RE = re.compile(r'(?:^|(?<=[\s(]))\\"[A-Za-z][^"]*?[A-Za-z.,!?]\\"')
# Caractère seul entre accolades : `S{é}ries`, `Poincar{é}`.
_BRACED_NON_ASCII_RE = re.compile(r"\{([^\x00-\x7f])\}")
_TRAILING_COMMAND_RE = re.compile(r"\\[A-Za-z]+$")
# Accolades vides qui terminent une lettre LaTeX : `\L{}ukasiewicz`.
_EMPTY_BRACES_AFTER_NON_ASCII_RE = re.compile(r"(?<=[^\x00-\x7f])\{\}")


def _prose_accented(m: re.Match[str]) -> str:
    """Comme `_accented`, en laissant les tournures de prose qui ressemblent à un accent : commande faite d'une lettre sans accolades (`Γ\\H b`, quotient par un groupe ; `\\c mu`), apostrophe échappée d'un possessif (`Allan\\'s`), accent sans caractère précomposé (`doesn\\'t`)."""
    command, bare = m.group(1), m.group(3)
    source, start, end = m.string, m.start(), m.end()
    wrapped = source[start - 1 : start] == "{" and source[end : end + 1] == "}"
    if bare and not wrapped:
        if command.isalpha():
            return m.group()
        possessive = (
            command == "'"
            and bare == "s"
            and source[start - 1 : start].isalpha()
            and not source[end : end + 1].isalpha()
        )
        if possessive:
            return m.group()
    accented = _accented(m)
    return accented if len(accented) == 1 else m.group()


def _prose_letter(m: re.Match[str]) -> str:
    """Convertit une lettre LaTeX de prose entre accolades (`{\\o}`), suivie d'accolades vides (`\\L{}`), ou `\\i` sous un accent (`\\'\\i`). Hors de ces formes, la commande reste (`(\\O)`, `2\\l`)."""
    source, start, end = m.string, m.start(), m.end()
    braced = source[start - 1 : start] == "{" and source[end : end + 1] == "}"
    emptied = source[end : end + 2] == "{}"
    under_accent = m.group(1) == "i" and re.search(r"\\[`'^\"~=.]\{?$", source[:start]) is not None
    return _LATEX_LETTERS[m.group(1)] if braced or emptied or under_accent else m.group()


def _unbraced(m: re.Match[str]) -> str:
    """Retire les accolades d'une lettre latine seule (`{à} la`), ou d'une lettre accolée à un mot (`S{é}ries`). Les accolades restent autour d'un ensemble (`∪ {∞}`, `({α})`), de l'argument d'une commande (`\\overline{Ω}`), d'un exposant ou d'un indice (`W^{±}`)."""
    character, before = m.group(1), m.string[: m.start()]
    if before.endswith(("^", "_")) or _TRAILING_COMMAND_RE.search(before):
        return m.group()
    in_word = before[-1:].isalpha() or m.string[m.end() : m.end() + 1].isalpha()
    latin = "LATIN" in unicodedata.name(character, "")
    return character if character.isalpha() and (latin or in_word) else m.group()


def _decode_prose_accents(segment: str) -> str:
    """Convertit les accents et les lettres LaTeX d'un passage de prose, et retire les accolades qui entourent seulement le caractère obtenu."""
    if "\\" in segment:
        segment = _DOUBLED_ACCENT_BACKSLASH_RE.sub(r"\\", segment)
        if _ESCAPED_QUOTE_PAIR_RE.search(segment):
            segment = segment.replace('\\"', '"')
        segment = _LATEX_LETTER_RE.sub(_prose_letter, segment)
        segment = _LATEX_ACCENT_RE.sub(_prose_accented, segment)
        segment = _EMPTY_BRACES_AFTER_NON_ASCII_RE.sub("", segment)
    return _BRACED_NON_ASCII_RE.sub(_unbraced, segment)


def _decode_prose_latex_accents(text: str) -> str:
    """Convertit les accents et les lettres LaTeX hors des formules. Les formules restent intactes."""
    if "\\" not in text and "{" not in text:
        return text
    parts: list[str] = []
    position = 0
    for formula in _MATH_SEGMENT_RE.finditer(text):
        parts += [_decode_prose_accents(text[position : formula.start()]), formula.group()]
        position = formula.end()
    parts.append(_decode_prose_accents(text[position:]))
    return "".join(parts)


_SINGLE_BACKSLASH_COMMAND_RE = re.compile(r"(?<!\\)\\[a-zA-Z]")


def _undouble_backslashes(text: str) -> str:
    """Divise par deux les barres obliques tant qu'aucune commande LaTeX n'est précédée d'une seule barre. Une source qui échappe son texte plusieurs fois multiplie les barres (`\\\\mathbf` chez OpenAlex, 64 barres dans des dépôts Crossref)."""
    while "\\\\" in text and not _SINGLE_BACKSLASH_COMMAND_RE.search(text):
        text = text.replace("\\\\", "\\")
    return text


def clean_source_text(text: str) -> str:
    """Nettoie un titre ou un résumé reçu d'une source, en gardant balises et formules : entités HTML décodées, barres obliques multipliées par un échappement répété ramenées à une, accents LaTeX hors formule convertis en caractères (`Th\\'eorie` → Théorie). L'espacement est laissé à l'appelant."""
    return _decode_prose_latex_accents(_undouble_backslashes(unescape_html(text)))


_ABSTRACT_SPACES_RE = re.compile(r"[ \t\r\f\v]+")
_ABSTRACT_LINE_EDGES_RE = re.compile(r" ?\n ?")
_ABSTRACT_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_abstract(abstract: str | None) -> str | None:
    """Nettoie un résumé à son écriture (`clean_source_text`). Les suites d'espaces ASCII se réduisent à un espace. Les sauts de ligne restent, et une ligne vide au plus sépare deux paragraphes. Les espaces insécables restent."""
    if not abstract:
        return abstract
    text = _ABSTRACT_SPACES_RE.sub(" ", clean_source_text(abstract))
    text = _ABSTRACT_LINE_EDGES_RE.sub("\n", text)
    return _ABSTRACT_BLANK_LINES_RE.sub("\n\n", text).strip()


def _byte_readings(byte: int) -> str:
    """Renvoie les caractères lus par Latin-1 et Windows-1252 pour `byte`. Ils diffèrent seulement de 0x80 à 0x9F, où Latin-1 lit un caractère de contrôle."""
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
# Expression des deux défauts d'encodage réparés par `repair_encoding`, valable aussi pour PostgreSQL.
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
    """Répare un encodage erroné : UTF-8 lu comme du Latin-1 ou du Windows-1252 (« TÃ©lesphore » → Télesphore), Windows-1252 lu comme du GBK (« Fran鏾is » → François)."""
    if text.isascii():
        return text
    return _CP1252_AS_GBK_RE.sub(_from_gbk, _UTF8_AS_CP1252_RE.sub(_from_utf8, text))


def sanitize_raw_text(text: str) -> str:
    """Renvoie le texte brut sans balisage, sans entités HTML ni caractères invisibles, espacement réduit à un espace simple. Casse, accents et ponctuation restent : le texte sert à l'affichage et à la recherche."""
    if not text:
        return ""
    text = to_plain_text(text)
    # `to_plain_text` réduit déjà l'espacement : un texte imprimable est déjà propre.
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
    """Nettoie la valeur d'un champ importé par `sanitize_raw_text` ; renvoie `None` si elle est vide."""
    return sanitize_raw_text(text or "") or None


_ASCII_SEPARATORS_RE = re.compile(r"[^a-z0-9]+")


def _drops_marks(base: str) -> bool:
    """Vrai quand les diacritiques qui suivent `base` se retirent : derrière une lettre latine ou grecque, ou derrière un caractère qui n'est pas une lettre. Ailleurs, ils distinguent des lettres (й, が)."""
    return not base.isalpha() or unicodedata.name(base, "").startswith(("LATIN", "GREEK"))


def _is_word_character(ch: str) -> bool:
    """Vrai pour une lettre ou un chiffre, hors lettres modificatives d'espacement (U+02B0–U+02FF) : apostrophe `ʼ`, okina `ʻ`, caron `ˇ` isolé d'une extraction PDF (« Maˇsek »)."""
    return ch.isalnum() and not "ʰ" <= ch <= "˿"


def normalize_text(text: str) -> str:
    """Renvoie la forme de comparaison d'un texte, pour le dédoublonnage et le rattachement : sans balises ni commandes LaTeX, en minuscules, ligatures et exposants décomposés (ﬁ → fi, ² → 2), sans diacritiques sur les lettres latines et grecques. Tout caractère autre qu'une lettre ou un chiffre devient un espace."""
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
# Parenthèses ou crochets vidés par le retrait des chiffres : « (1278759) », « (1960-2020) ».
_EMPTY_BRACKETS_RE = re.compile(r"[(\[][^\w()\[\]]*[)\]]")
# Mot fait de ponctuation seule : le tiret de « Wolff, Charlotta 1976- », isolé par le retrait des chiffres.
_PUNCTUATION_ONLY_RE = re.compile(r"[^\w\s'’]+")
# Séparateurs en fin de nom : la virgule de « D'Andrea, Carlos, 1973- ». Le point d'une initiale reste.
_TRAILING_SEPARATORS = ",;:-–—/"


def clean_raw_author_name(raw: str) -> str:
    """Nettoie un nom d'auteur brut : balisage et chiffres retirés, accents LaTeX et encodage réparés. La ponctuation isolée par le retrait des chiffres disparaît aussi.

    Les chiffres d'un nom sont une année de naissance (« Candoni, Jean-François 1964- »), un identifiant de source ou un renvoi d'affiliation (« Ibrahim1 »). Un nom fait seulement de chiffres et de ponctuation reste tel quel.
    """
    if not raw:
        return raw
    text = decode_latex_accents(repair_encoding(to_plain_text(raw)))
    # Accolades de groupement LaTeX restées sans commande : « Geß{}ner ».
    text = text.replace("{", "").replace("}", "")
    cleaned = " ".join(_EMPTY_BRACKETS_RE.sub(" ", _DIGITS_RE.sub("", text)).split())
    # Parenthèse détachée de son contenu par le retrait des chiffres : « (EA 999) » → « (EA) ».
    cleaned = cleaned.replace(" )", ")").replace(" ]", "]")
    words = [word for word in cleaned.split(" ") if not _PUNCTUATION_ONLY_RE.fullmatch(word)]
    cleaned = " ".join(words).rstrip(_TRAILING_SEPARATORS).strip()
    return cleaned or " ".join(text.split())
