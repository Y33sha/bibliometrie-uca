import DOMPurify from 'dompurify';
import katex from 'katex';

/** Sérialise des paramètres en query string en gardant les virgules littérales. `URLSearchParams.toString()` percent-encode la virgule en `%2C` ; or elle est licite dans une query (RFC 3986) et sépare nos listes de valeurs — on la restaure pour des URL lisibles. Retourne la chaîne sans le `?` initial (vide si aucun paramètre). */
export function paramsToQuery(params: URLSearchParams): string {
	return params.toString().replace(/%2C/g, ',');
}

/* ── sanitizeTitle ─────────────────────────────────────────────
 * Rend les titres de publication, qui peuvent contenir :
 *  - du MathML au préfixe de namespace mml:  (<mml:msup>, <mml:mi>, …)
 *  - des maths LaTeX en ligne ou hors-texte   ($...$, $$...$$)
 *  - du formatage HTML simple                 (<sub>, <sup>, <i>)
 *
 * Les segments LaTeX sont rendus via KaTeX ; le MathML voit son préfixe mml: retiré pour un rendu natif par le navigateur. Seule une liste blanche de balises/attributs sûrs est conservée, le reste est échappé (sûr vis-à-vis du XSS → à utiliser avec {@html}).
 * ────────────────────────────────────────────────────────────── */

const TITLE_ALLOWED_TAGS = new Set([
	'sub', 'sup', 'i', 'em',
	'math', 'msup', 'msub', 'msubsup', 'mi', 'mn', 'mo', 'mrow',
	'msqrt', 'mfrac', 'mspace', 'mover', 'munder', 'munderover',
	'mtext', 'mpadded', 'mphantom', 'mtable', 'mtr', 'mtd',
	'menclose', 'mstyle', 'merror'
]);

/* Le résumé porte en plus la structure que les sources y déposent (JATS, Crossref) : paragraphes et intertitres en gras (« Background: »). */
const ABSTRACT_ALLOWED_TAGS = new Set([...TITLE_ALLOWED_TAGS, 'p', 'br', 'b']);

const TITLE_ALLOWED_ATTRS = new Set(['mathvariant', 'display']);

/* Lettres grecques du paquet upgreek, qui les compose droites (usage pour les noms de particules). KaTeX les rend en italique. */
const GREEK_LETTERS = [
	'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'varepsilon', 'zeta', 'eta', 'theta', 'vartheta',
	'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'pi', 'varpi', 'rho', 'varrho', 'sigma', 'varsigma',
	'tau', 'upsilon', 'phi', 'varphi', 'chi', 'psi', 'omega',
	'Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma', 'Upsilon', 'Phi', 'Psi', 'Omega'
];

/* Macros présentes dans les formules des sources et absentes de KaTeX, qui les afficherait en rouge. */
const KATEX_MACROS: Record<string, string | object> = {
	// Commandes LaTeX standard.
	'\\mbox': '\\text{#1}',
	'\\ensuremath': '#1',
	'\\hfill': '',
	'\\textless': '<',
	'\\textgreater': '>',
	'\\arrowvert': '\\vert',
	'\\nulldelimiterspace': '1.2pt',
	'\\label': { tokens: [], numArgs: 1 },
	// Classes LaTeX de Springer.
	'\\varvec': '\\boldsymbol',
	// Abréviations d'usage courant dans les macros d'auteurs.
	'\\C': '\\mathbb{C}',
	'\\eps': '\\varepsilon',
	'\\pa': '\\partial',
	'\\Cal': '\\mathcal',
	'\\cE': '\\mathcal{E}',
	'\\dsp': '\\displaystyle',
	'\\re': '\\operatorname{Re}',
	'\\Log': '\\operatorname{Log}',
	'\\conv': '\\operatorname{conv}',
	'\\diam': '\\operatorname{diam}',
	...Object.fromEntries(
		GREEK_LETTERS.map((name) => [
			name[0] === name[0].toUpperCase() ? `\\Up${name.toLowerCase()}` : `\\up${name}`,
			`\\${name}`
		])
	)
};

/* Caractère désigné par son code (`\unicode[STIX]{x1D70E}`, extension MathJax), en hexadécimal ou en décimal. */
const UNICODE_COMMAND = /\\unicode\s*(?:\[[^\]]*\])?\s*\{\s*(?:0?x([0-9a-fA-F]+)|(\d+))\s*\}/g;

/* Condition TeX sur le mode mathématique : seule la branche mathématique concerne une formule. */
const IFMMODE = /\\ifmmode\s*([\s\S]*?)\\else[\s\S]*?\\fi/g;

const EQNARRAY = /\\(begin|end)\{eqnarray\*?\}/g;

/* Environnements et numéros d'équation que KaTeX rend seulement en mode bloc. */
const DISPLAY_ONLY = /\\begin\{(equation|align|alignat|gather)\*?\}|\\tag\*?\s*\{/;

/* Réécrit les tournures des sources que KaTeX ne lit pas. Un caractère mathématique Unicode (𝛼, absent des polices de KaTeX) devient sa lettre de base (α). `eqnarray` devient un tableau aux mêmes colonnes. */
function adaptTex(tex: string): string {
	return tex
		.replace(UNICODE_COMMAND, (full, hex: string | undefined, decimal: string | undefined) => {
			const code = hex !== undefined ? parseInt(hex, 16) : parseInt(decimal!, 10);
			return code <= 0x10ffff ? String.fromCodePoint(code).normalize('NFKC') : full;
		})
		.replace(IFMMODE, '$1')
		.replace(EQNARRAY, (_full, side: string) => (side === 'begin' ? '\\begin{array}{rcl}' : '\\end{array}'));
}

/* Commandes de gras des formules. Une revue qui compose ses titres en gras y met aussi leurs formules : ce gras est sans valeur. */
const UNBOLD_MACROS: Record<string, string> = {
	'\\mathbf': '#1',
	'\\boldsymbol': '#1',
	'\\bm': '#1',
	'\\pmb': '#1',
	'\\varvec': '#1',
	'\\textbf': '\\text{#1}',
	'\\bf': ''
};

/* Ensemble de nombres en gras (`\mathbf{Z}`) : seul gras de titre qui porte un sens. Il passe en lettre ajourée (ℤ), notation équivalente. */
const BOLD_NUMBER_SET = /\\mathbf\s*\{\s*([NZQRC])\s*\}/g;

/* Variantes grasses du MathML : `bold` donne la variante par défaut, `bold-italic` donne `italic`. */
const MATHML_BOLD = /\smathvariant\s*=\s*(["'])bold\1|(mathvariant\s*=\s*["'])bold-/g;

function unboldMathml(s: string): string {
	return s.replace(MATHML_BOLD, (_full, _quote, prefix: string | undefined) => prefix ?? '');
}

/* Règles de rendu d'un type de texte. Un titre perd son gras, balises HTML comprises ; un résumé le garde. */
interface RenderRules {
	allowedTags: Set<string>;
	keepsBold: boolean;
}

const TITLE_RULES: RenderRules = { allowedTags: TITLE_ALLOWED_TAGS, keepsBold: false };
const ABSTRACT_RULES: RenderRules = { allowedTags: ABSTRACT_ALLOWED_TAGS, keepsBold: true };

function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

/* Segment délimité par des dollars : $$...$$ (hors-texte) ou $...$ (en ligne). */
const LATEX_SEGMENT = /\$\$([\s\S]+?)\$\$|\$([^$]+?)\$/g;

const WORD_RE = /[A-Za-zÀ-ÿ]{3,}/g;

/* Vrai si le contenu délimité est de la prose prise entre deux dollars de monnaie, non une formule.
 *
 * Un abstract qui cite un montant (« $39.43 for treatment. About 18% of patients... $12 ») offre
 * deux dollars au délimiteur, et tout ce qui les sépare partirait chez KaTeX. Une commande LaTeX
 * (`\`) tranche la question ; à défaut, trois mots ou plus désignent de la prose. Mesuré sur le
 * corpus : aucun titre écarté, trente segments d'abstract écartés, tous de la prose. */
function isProse(content: string): boolean {
	if (content.includes('\\')) return false;
	return (content.match(WORD_RE) ?? []).length >= 3;
}

/* Vrai si la chaîne porte au moins un segment de maths — un montant en dollars n'en fait pas une. */
function hasLatex(s: string): boolean {
	LATEX_SEGMENT.lastIndex = 0;
	let m;
	while ((m = LATEX_SEGMENT.exec(s)) !== null) {
		if (!isProse(m[1] || m[2])) return true;
	}
	return false;
}

/* Dédouble les barres obliques d'une formule échappée deux fois par sa source (`\\rm{K}`) : toutes ses commandes y sont précédées de deux barres. Une formule qui contient une commande à barre simple garde ses `\\`, sauts de ligne d'un tableau ou d'un environnement. */
function undoubleBackslashes(tex: string): string {
	return /(^|[^\\])\\[a-zA-Z]/.test(tex) ? tex : tex.replace(/\\\\/g, '\\');
}

/* Rend les segments LaTeX via KaTeX. Le texte qui les entoure passe par la liste blanche plutôt
 * que par un échappement en bloc : un résumé qui porte à la fois des paragraphes et une formule
 * garde les deux. Les segments de prose, eux, gardent leurs dollars — ce sont des caractères du
 * texte, non des délimiteurs. */
function renderLatex(s: string, rules: RenderRules): string {
	const parts: string[] = [];
	let lastIdx = 0;
	LATEX_SEGMENT.lastIndex = 0;
	let m;

	while ((m = LATEX_SEGMENT.exec(s)) !== null) {
		parts.push(sanitizeMarkup(s.slice(lastIdx, m.index), rules.allowedTags));
		const content = m[1] || m[2];
		if (isProse(content)) {
			parts.push(escapeHtml(m[0]));
		} else {
			let tex = adaptTex(undoubleBackslashes(content.trim()));
			if (!rules.keepsBold) tex = tex.replace(BOLD_NUMBER_SET, '\\mathbb{$1}');
			// Une formule détachée (`$$`) de plusieurs lignes s'affiche en bloc, comme une formule réservée au bloc ; les autres restent dans la phrase.
			const displayMode = DISPLAY_ONLY.test(tex) || (m[1] !== undefined && tex.includes('\\\\'));
			try {
				parts.push(katex.renderToString(tex, {
					displayMode,
					throwOnError: false,
					// Copie fraîche à chaque formule : KaTeX y enregistre les `\def` qu'il rencontre.
					macros: rules.keepsBold ? { ...KATEX_MACROS } : { ...KATEX_MACROS, ...UNBOLD_MACROS }
				}));
			} catch {
				parts.push(escapeHtml(tex));
			}
		}
		lastIdx = m.index + m[0].length;
	}

	parts.push(sanitizeMarkup(s.slice(lastIdx), rules.allowedTags));
	return parts.join('');
}

/* Assainit le MathML et les balises de formatage HTML par liste blanche, via DOMPurify. */
function sanitizeMarkup(s: string, allowedTags: Set<string>): string {
	// Retire le préfixe de namespace `mml:` pour un rendu MathML natif par le navigateur.
	const input = s.replace(/<(\/?)\s*mml:/g, '<$1');
	return DOMPurify.sanitize(input, {
		ALLOWED_TAGS: [...allowedTags],
		ALLOWED_ATTR: [...TITLE_ALLOWED_ATTRS]
	});
}

const HAS_MATHML = /<\/?mml:/;

const ENTITY_MAP: Record<string, string> = {
	amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"
};

/* Décode une couche d'entités HTML (nommées + numériques). */
function decodeEntitiesOnce(s: string): string {
	return s.replace(
		/&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);/gi,
		(full, entity: string) => {
			if (entity[0] === '#') {
				const code = entity[1] === 'x' || entity[1] === 'X'
					? parseInt(entity.slice(2), 16)
					: parseInt(entity.slice(1), 10);
				return Number.isFinite(code) ? String.fromCodePoint(code) : full;
			}
			return ENTITY_MAP[entity.toLowerCase()] ?? full;
		}
	);
}

/* Décode les entités HTML d'un titre jusqu'à stabilisation (`&lt;sub&gt;` → `<sub>`, `&amp;` → `&`, `&#233;` → `é`). La boucle (bornée) absorbe le double-encodage (`&amp;lt;`). Le markup brut obtenu est ensuite sanitizé ; un `&` de contenu est ré-échappé par `escapeHtml`. */
function decodeHtmlEntities(s: string): string {
	let out = s;
	for (let i = 0; i < 4; i++) {
		const decoded = decodeEntitiesOnce(out);
		if (decoded === out) break;
		out = decoded;
	}
	return out;
}

/* Rend une chaîne reçue d'une source, sûre vis-à-vis du XSS, selon les règles de son type de texte. */
function render(s: string | null | undefined, rules: RenderRules): string {
	if (!s) return '';

	let input = decodeHtmlEntities(s);
	if (!rules.keepsBold) input = unboldMathml(input);

	if (hasLatex(input)) return renderLatex(input, rules);
	if (HAS_MATHML.test(input) || /<\/?[a-z]/i.test(input)) return sanitizeMarkup(input, rules.allowedTags);

	return escapeHtml(input);
}

export function sanitizeTitle(s: string | null | undefined): string {
	return render(s, TITLE_RULES);
}

/** Texte visible du rendu de `sanitizeTitle`, pour les emplacements qui n'acceptent pas de HTML (titre d'onglet, info-bulle). La copie MathML que KaTeX joint à son rendu est écartée. */
export function titleText(s: string | null | undefined): string {
	const doc = new DOMParser().parseFromString(sanitizeTitle(s), 'text/html');
	doc.querySelectorAll('.katex-mathml').forEach((node) => node.remove());
	return (doc.body.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/* Comme `sanitizeTitle`, en gardant les paragraphes : un résumé en porte, un titre non. */
export function sanitizeAbstract(s: string | null | undefined): string {
	return render(s, ABSTRACT_RULES);
}

export function titleCase(s: string | null | undefined): string {
	if (!s) return '';
	return s
		.split(/(\s+|[-\u2010\u2011\u2012\u2013\u2014''])/g)
		.map((w) => (/^[\s\-\u2010-\u2014'']+$/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()))
		.join('');
}

export function formatDate(d: string | null | undefined): string {
	if (!d) return '';
	const parts = d.split('-');
	if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
	return d;
}

/** Dépôts HAL d'un compte auteur. HAL indexe le `personId` du compte sous `authIdHal_i`. */
export function halPersonUrl(halPersonId: string | number): string {
	return `https://hal.science/search/index/?qa%5BauthIdHal_i%5D%5B%5D=${halPersonId}`;
}

/** Identifiant ROR court (sans le préfixe https://ror.org/). */
export function rorShortId(rorId: string): string {
	return rorId.replace('https://ror.org/', '');
}

/** URL canonique d'une organisation sur ror.org (accepte un id court ou une URL complète). */
export function rorFullUrl(rorId: string): string {
	if (rorId.startsWith('http')) return rorId;
	return `https://ror.org/${rorId}`;
}

/** Dérive le statut de détection d'une structure à partir des flags `is_confirmed` (tri-state nullable) et `is_detected` (booléen).
 *
 * Règle : confirmed > rejected > detected > manual.
 *  - `is_confirmed === true`  → confirmed (validée manuellement)
 *  - `is_confirmed === false` → rejected (invalidée manuellement)
 *  - `is_detected`            → detected (trouvée par le script, non revue)
 *  - sinon                    → manual (saisie manuelle sans détection)
 */
export function deriveStructDetectionStatus(
	isConfirmed: boolean | null | undefined,
	isDetected: boolean | null | undefined
): 'confirmed' | 'rejected' | 'detected' | 'manual' {
	if (isConfirmed === true) return 'confirmed';
	if (isConfirmed === false) return 'rejected';
	if (isDetected) return 'detected';
	return 'manual';
}
