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
	'sub', 'sup', 'i', 'b', 'em',
	'math', 'msup', 'msub', 'msubsup', 'mi', 'mn', 'mo', 'mrow',
	'msqrt', 'mfrac', 'mspace', 'mover', 'munder', 'munderover',
	'mtext', 'mpadded', 'mphantom', 'mtable', 'mtr', 'mtd',
	'menclose', 'mstyle', 'merror'
]);

/* Le résumé porte en plus la structure de paragraphe que les sources y déposent (JATS, Crossref).
 * La perdre collerait tout le texte en un bloc. */
const ABSTRACT_ALLOWED_TAGS = new Set([...TITLE_ALLOWED_TAGS, 'p', 'br']);

const TITLE_ALLOWED_ATTRS = new Set(['mathvariant', 'display']);

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

/* Rend les segments LaTeX via KaTeX. Le texte qui les entoure passe par la liste blanche plutôt
 * que par un échappement en bloc : un résumé qui porte à la fois des paragraphes et une formule
 * garde les deux. Les segments de prose, eux, gardent leurs dollars — ce sont des caractères du
 * texte, non des délimiteurs. */
function renderLatex(s: string, allowedTags: Set<string>): string {
	const parts: string[] = [];
	let lastIdx = 0;
	LATEX_SEGMENT.lastIndex = 0;
	let m;

	while ((m = LATEX_SEGMENT.exec(s)) !== null) {
		parts.push(sanitizeMarkup(s.slice(lastIdx, m.index), allowedTags));
		const content = m[1] || m[2];
		if (isProse(content)) {
			parts.push(escapeHtml(m[0]));
		} else {
			const tex = content.trim().replace(/\\\\/g, '\\');
			try {
				parts.push(katex.renderToString(tex, {
					displayMode: false,
					throwOnError: false
				}));
			} catch {
				parts.push(escapeHtml(tex));
			}
		}
		lastIdx = m.index + m[0].length;
	}

	parts.push(sanitizeMarkup(s.slice(lastIdx), allowedTags));
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

/* Rend une chaîne reçue d'une source, sûre vis-à-vis du XSS, en n'autorisant que `allowedTags`. */
function render(s: string | null | undefined, allowedTags: Set<string>): string {
	if (!s) return '';

	const input = decodeHtmlEntities(s);

	if (hasLatex(input)) return renderLatex(input, allowedTags);
	if (HAS_MATHML.test(input) || /<\/?[a-z]/i.test(input)) return sanitizeMarkup(input, allowedTags);

	return escapeHtml(input);
}

export function sanitizeTitle(s: string | null | undefined): string {
	return render(s, TITLE_ALLOWED_TAGS);
}

/* Comme `sanitizeTitle`, en gardant les paragraphes : un résumé en porte, un titre non. */
export function sanitizeAbstract(s: string | null | undefined): string {
	return render(s, ABSTRACT_ALLOWED_TAGS);
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

export function halDocUrl(halid: string, oaStatus?: string | null): string {
	if (halid.startsWith('dumas-')) return `https://dumas.ccsd.cnrs.fr/${halid}`;
	if (halid.startsWith('tel-') && oaStatus !== 'closed') return `https://theses.hal.science/${halid}`;
	return `https://hal.science/${halid}`;
}

export function scanrPubUrl(scanrId: string): string {
	return `https://scanr.enseignementsup-recherche.gouv.fr/publications/${encodeURIComponent(scanrId)}`;
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
