"""Nettoyage des textes reçus des sources, et forme de comparaison des textes."""

import html
import re
import unicodedata

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
"""Lettres non décomposées par NFKD, ramenées à leur forme sans diacritique : « Meyerhofstraße » et « Meyerhofstrasse » ont la même forme normalisée. Appliquée après lower()."""


_MARKUP_RE = re.compile(r"</?([A-Za-z][^\s<>/]*)(?:[\s/][^<>]*)?>")
"""Balise : `<` suivi d'une lettre ou de `/`. Le corps exclut `<` : une suite de `<` sans fermeture se parcourt en temps linéaire."""

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
"""Balises de mise en forme (HTML, JATS, MathML), qui s'insèrent dans un mot : `CO<sub>2</sub>`, `<i>E</i>. coli`. Comparées sans préfixe d'espace de noms (`jats:sub`, `mml:mi`)."""


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


_MAX_UNESCAPE_PASSES = 4
"""Certaines sources échappent plusieurs fois une valeur (`&amp;amp;`)."""


def _unescape_html(text: str) -> str:
    """Décode les entités HTML jusqu'à stabilisation."""
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


_INVISIBLE_CATEGORIES = frozenset({"Cf", "Cc", "Cs", "Co"})
"""Caractères invisibles : formatage (espace sans chasse), contrôle, substituts isolés, usage privé."""


def to_plain_text(text: str | None) -> str:
    """Renvoie le texte brut d'une valeur reçue d'une source : commentaires, balises, entités HTML et caractères invisibles retirés, espacement réduit à un espace simple. Une balise échappée (`&lt;p&gt;`) est retirée aussi. Casse, accents et ponctuation restent."""
    if not text:
        return ""
    plain = _strip_markup(_strip_comments(_unescape_html(text)))
    if not plain.isprintable():
        plain = "".join(
            ch
            for ch in plain
            if ch.isspace() or unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
        )
    return " ".join(plain.split())


def optional_plain_text(text: str | None) -> str | None:
    """Renvoie le texte brut de `text` (`to_plain_text`), ou `None` s'il est vide."""
    return to_plain_text(text) or None


_MAX_MARKUP_PASSES = 8
"""Le retrait d'une balise imbriquée (`<ab<aa>a>`) en reconstitue une autre. Chaque passe coûte un parcours du texte."""


def _strip_markup(text: str) -> str:
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
    """Retire du titre la version MathML de ses formules, et les espaces de bordure.

    Un éditeur dépose chaque formule d'un titre en deux versions : LaTeX (`$$…$$`) et MathML. Crossref renvoie le titre avec l'indentation du XML déposé et sans les balises MathML. La formule LaTeX occupe une ligne. Chaque symbole MathML occupe une ligne d'indentation supérieure, avant ou après. ScanR recopie ce titre. Ces lignes de symboles isolés sont retirées. L'interface affiche la formule LaTeX.

    Un titre déjà mis sur une ligne ne garde aucun repère : il reste tel quel.
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
    return "\n".join(line for k, line in enumerate(lines) if k not in dropped).strip()


_MATHML_FORMULA = r"<mml:math\b(?:(?!<mml:math\b).)*?(?:</mml:math>|\Z)"
"""Formule MathML. Son corps exclut une autre ouverture. La fin du texte ferme une formule : OpenAlex tronque des résumés en pleine formule."""
_TEX_THEN_MATHML_RE = re.compile(rf"(\$\$[^$]+\$\$)(?:\s*{_MATHML_FORMULA})+", re.DOTALL)
"""Formules LaTeX `$$…$$` suivies de leurs versions MathML, sans texte entre elles."""
_MATHML_FORMULA_RE = re.compile(_MATHML_FORMULA, re.DOTALL)
_TEX_ANNOTATION_RE = re.compile(
    r'<mml:annotation\b[^>]*encoding="application/x-tex"[^>]*>(.*?)</mml:annotation>', re.DOTALL
)


def _annotation_tex(match: re.Match[str]) -> str:
    """Renvoie la version LaTeX `$$…$$` de l'annotation de la formule, la formule à défaut."""
    annotation = _TEX_ANNOTATION_RE.search(match.group())
    return f"$${annotation.group(1).strip()}$$" if annotation else match.group()


def _drop_duplicate_mathml(abstract: str | None) -> str | None:
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
_ABSTRACT_LABEL_RE = re.compile(
    rf"^\s*(?:<(?:jats:)?title>\s*(?:{_ABSTRACT_LABEL})\s*[.:]?\s*</(?:jats:)?title>\s*"
    rf"|(?:{_ABSTRACT_LABEL})(?:\s*[.:：–—-]\s*|\s+(?=[A-ZÀ-ÖØ-Þ0-9(\[<$«\"“])))"
)
"""Intitulé seul dans une balise de titre, suivi d'une ponctuation, ou suivi d'une majuscule, d'un chiffre ou d'une formule."""


_MAX_ABSTRACT_LABELS = 3
"""Intitulés empilés en tête d'un même résumé : « Abstract Summary »."""


def _strip_abstract_label(abstract: str | None) -> str | None:
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

_LATEX_ACCENT_RE = re.compile(
    r"\\([`'^\"~=.]|[cvuHkrCVUKR](?=[\s{]))(?:\{\s*([A-Za-zı])\s*\}|\s*([A-Za-zı]))"
)
"""Accent LaTeX sur une lettre : `\\'e`, `\\'{e}`, `\\c{c}`, `\\v c`. Groupe 1 : la commande d'accent ; groupe 2 ou 3 : la lettre. Les commandes faites d'une lettre (`\\c`, `\\v`) sont suivies d'une accolade ou d'une espace. Une source qui met un nom en majuscules met aussi la commande (`Gon\\C Calo`)."""
_LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_LATEX_ACCENTS = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
    ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328",
    "r": "\u030a", "U": "\u0306", "V": "\u030c", "C": "\u0327", "K": "\u0328", "R": "\u030a",
}  # fmt: skip
"""Diacritique combinant de chaque commande d'accent."""
_LATEX_LETTERS = {
    "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "ss": "ß", "Ss": "ß",
    "SS": "ß", "o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "i": "ı",
}  # fmt: skip
"""Lettres LaTeX sans équivalent ASCII : `\\o` → ø, `\\ss` → ß. `\\i` est le i sans point, qui reçoit un accent (`\\'{\\i}`)."""
_LATEX_LETTER_RE = re.compile(r"\\(ss|Ss|SS|(?:aa|AA|ae|AE|oe|OE|[oOlLi])(?![A-Za-z]))")
"""`\\ss` se reconnaît même collé au reste du mot (`Ge\\ssner`) : aucune autre commande ne commence par ss."""


def _strip_latex(text: str) -> str:
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


def _decode_latex_accents(text: str) -> str:
    """Convertit les accents et les lettres LaTeX en caractères : `Fr\\'ed\\'eric` → Frédéric, `Besan\\c{c}on` → Besançon, `J{\\o}rgensen` → J{ø}rgensen."""
    if "\\" not in text:
        return text
    text = _LATEX_LETTER_RE.sub(lambda m: _LATEX_LETTERS[m.group(1)], text)
    return unicodedata.normalize("NFC", _LATEX_ACCENT_RE.sub(_accented, text))


_MATH_SEGMENT_RE = re.compile(r"\$\$[\s\S]+?\$\$|\$[^$]+?\$")
"""Formule délimitée par des dollars : $$...$$ ou $...$."""
_DOUBLED_ACCENT_BACKSLASH_RE = re.compile(r"\\\\(?=[`'^\"~=.]|[cvuHkrCVUKR]\{)")
"""Barre oblique doublée devant une commande d'accent, laissée par un texte échappé deux fois dont une autre commande a gardé sa barre simple."""
_ESCAPED_QUOTE_PAIR_RE = re.compile(r'(?:^|(?<=[\s(]))\\"[A-Za-z][^"]*?[A-Za-z.,!?]\\"')
"""Paire de guillemets échappés (`the \\"cold\\" case`) : les `\\"` du texte sont des guillemets, non des trémas."""
_BRACED_NON_ASCII_RE = re.compile(r"\{([^\x00-\x7f])\}")
"""Caractère seul entre accolades : `S{é}ries`, `Poincar{é}`."""
_TRAILING_COMMAND_RE = re.compile(r"\\[A-Za-z]+$")
_EMPTY_BRACES_AFTER_NON_ASCII_RE = re.compile(r"(?<=[^\x00-\x7f])\{\}")
"""Accolades vides qui terminent une lettre LaTeX : `\\L{}ukasiewicz`."""


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


def _clean_source_text(text: str) -> str:
    """Nettoyage commun aux titres et aux résumés, hors espacement (`clean_title`)."""
    return _decode_prose_latex_accents(_undouble_backslashes(_unescape_html(text)))


_ASCII_SPACES_RE = re.compile(r"[ \t\n\r\f\v]+")
"""Espaces ASCII seuls : les espaces insécables de la typographie (« pratiques : ») restent."""


def clean_title(title: str | None) -> str | None:
    """Nettoie un titre à son écriture, en gardant balises et formules : entités HTML décodées, barres obliques multipliées par un échappement répété ramenées à une, accents LaTeX hors formule convertis en caractères (`Th\\'eorie` → Théorie). Les suites d'espaces ASCII se réduisent à un espace, les espaces de bordure sont retirés. Les espaces insécables restent."""
    if not title:
        return title
    return _ASCII_SPACES_RE.sub(" ", _clean_source_text(title)).strip()


_ABSTRACT_SPACES_RE = re.compile(r"[ \t\r\f\v]+")
_ABSTRACT_LINE_EDGES_RE = re.compile(r" ?\n ?")
_ABSTRACT_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_abstract(abstract: str | None) -> str | None:
    """Nettoie un résumé à son écriture, comme un titre (`clean_title`), en gardant ses sauts de ligne : une ligne vide au plus sépare deux paragraphes. La version MathML d'une formule déposée aussi en LaTeX est retirée, ainsi que l'intitulé « Abstract » ou « Résumé » en tête."""
    if not abstract:
        return abstract
    text = _ABSTRACT_SPACES_RE.sub(" ", _clean_source_text(abstract))
    text = _ABSTRACT_LINE_EDGES_RE.sub("\n", text)
    text = _ABSTRACT_BLANK_LINES_RE.sub("\n\n", text).strip()
    return _strip_abstract_label(_drop_duplicate_mathml(text))


def _byte_readings(byte: int) -> str:
    """Renvoie les caractères lus par Latin-1 et Windows-1252 pour `byte`. Ils diffèrent seulement de 0x80 à 0x9F, où Latin-1 lit un caractère de contrôle."""
    try:
        return chr(byte) + bytes([byte]).decode("cp1252")
    except UnicodeDecodeError:
        return chr(byte)


_BYTES = {c: b for b in range(0x80, 0x100) for c in _byte_readings(b)}
"""Octets 0x80 à 0xFF, indexés par leurs lectures Latin-1 et Windows-1252."""
_CONTINUATION = "".join(_byte_readings(b) for b in range(0x80, 0xC0))
_UTF8_AS_CP1252_RE = re.compile(
    f"[Â-ß][{_CONTINUATION}]|[à-ï][{_CONTINUATION}]{{2}}|[ð-ô][{_CONTINUATION}]{{3}}"
)
"""Caractère UTF-8 lu comme du Latin-1 ou du Windows-1252 : un octet de tête, puis autant d'octets de continuation qu'il en annonce."""
_CP1252_AS_GBK_RE = re.compile("(?<=[A-Za-z])[一-鿿]+")
"""Texte Windows-1252 lu comme du GBK : une lettre accentuée et la lettre ASCII qui la suit forment un idéogramme, collé à une lettre latine."""


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


def _repair_encoding(text: str) -> str:
    """Répare un encodage erroné : UTF-8 lu comme du Latin-1 ou du Windows-1252 (« TÃ©lesphore » → Télesphore), Windows-1252 lu comme du GBK (« Fran鏾is » → François)."""
    if text.isascii():
        return text
    return _CP1252_AS_GBK_RE.sub(_from_gbk, _UTF8_AS_CP1252_RE.sub(_from_utf8, text))


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
    text = _strip_latex(_strip_markup(text)).lower()
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
_EMPTY_BRACKETS_RE = re.compile(r"[(\[][^\w()\[\]]*[)\]]")
"""Parenthèses ou crochets vidés par le retrait des chiffres : « (1278759) », « (1960-2020) »."""
_PUNCTUATION_ONLY_RE = re.compile(r"[^\w\s'’]+")
"""Mot fait de ponctuation seule : le tiret de « Wolff, Charlotta 1976- », isolé par le retrait des chiffres."""
_TRAILING_SEPARATORS = ",;:-–—/"
"""Séparateurs en fin de nom : la virgule de « D'Andrea, Carlos, 1973- ». Le point d'une initiale reste."""


def clean_raw_author_name(raw: str) -> str:
    """Nettoie un nom d'auteur brut : balisage et chiffres retirés, accents LaTeX et encodage réparés. La ponctuation isolée par le retrait des chiffres disparaît aussi.

    Les chiffres d'un nom sont une année de naissance (« Candoni, Jean-François 1964- »), un identifiant de source ou un renvoi d'affiliation (« Ibrahim1 »). Un nom fait seulement de chiffres et de ponctuation reste tel quel.
    """
    if not raw:
        return raw
    # L'encodage se répare avant le retrait des caractères invisibles : « GroÃ\x9f » contient un contrôle C1.
    text = _decode_latex_accents(to_plain_text(_repair_encoding(raw)))
    # Accolades de groupement LaTeX : « J{\o}rgensen », « Geß{}ner ».
    text = text.replace("{", "").replace("}", "")
    cleaned = " ".join(_EMPTY_BRACKETS_RE.sub(" ", _DIGITS_RE.sub("", text)).split())
    # Parenthèse détachée de son contenu par le retrait des chiffres : « (EA 999) » → « (EA) ».
    cleaned = cleaned.replace(" )", ")").replace(" ]", "]")
    words = [word for word in cleaned.split(" ") if not _PUNCTUATION_ONLY_RE.fullmatch(word)]
    cleaned = " ".join(words).rstrip(_TRAILING_SEPARATORS).strip()
    return cleaned or " ".join(text.split())
