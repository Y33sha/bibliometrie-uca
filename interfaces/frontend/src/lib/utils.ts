import katex from 'katex';

export function esc(s: string | null | undefined): string {
	if (!s) return '';
	const d = document.createElement('div');
	d.textContent = s;
	return d.innerHTML;
}

/* ── sanitizeTitle ─────────────────────────────────────────────
 * Renders publication titles that may contain:
 *  - MathML with mml: namespace prefix  (<mml:msup>, <mml:mi>, …)
 *  - LaTeX inline/display math          ($...$, $$...$$)
 *  - Plain HTML formatting              (<sub>, <sup>, <i>)
 *
 * LaTeX segments are rendered via KaTeX.
 * MathML: strips the mml: prefix for native browser rendering.
 * Keeps only an allowlist of safe tags/attributes, and escapes
 * everything else (XSS-safe → use with {@html}).
 * ────────────────────────────────────────────────────────────── */

const TITLE_ALLOWED_TAGS = new Set([
	'sub', 'sup', 'i', 'b', 'em',
	'math', 'msup', 'msub', 'msubsup', 'mi', 'mn', 'mo', 'mrow',
	'msqrt', 'mfrac', 'mspace', 'mover', 'munder', 'munderover',
	'mtext', 'mpadded', 'mphantom', 'mtable', 'mtr', 'mtd',
	'menclose', 'mstyle', 'merror'
]);

const TITLE_ALLOWED_ATTRS = new Set(['mathvariant', 'display']);

function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

/* Render LaTeX $...$ and $$...$$ segments via KaTeX,
 * escape all non-LaTeX text. */
function renderLatex(s: string): string {
	const parts: string[] = [];
	let lastIdx = 0;
	// Match $$...$$ (display) then $...$ (inline)
	const re = /\$\$([\s\S]+?)\$\$|\$([^$]+?)\$/g;
	let m;

	while ((m = re.exec(s)) !== null) {
		parts.push(escapeHtml(s.slice(lastIdx, m.index)));
		const tex = (m[1] || m[2]).trim().replace(/\\\\/g, '\\');
		try {
			parts.push(katex.renderToString(tex, {
				displayMode: false,
				throwOnError: false
			}));
		} catch {
			parts.push(escapeHtml(tex));
		}
		lastIdx = m.index + m[0].length;
	}

	parts.push(escapeHtml(s.slice(lastIdx)));
	return parts.join('');
}

/* Sanitize MathML + HTML formatting tags. */
function sanitizeMathML(s: string): string {
	const input = s.replace(/<(\/?)\s*mml:/g, '<$1');

	const parts: string[] = [];
	let lastIdx = 0;
	const re = /<(\/?)(\w+)(\s[^>]*)?\s*\/?>/g;
	let m;

	while ((m = re.exec(input)) !== null) {
		parts.push(escapeHtml(input.slice(lastIdx, m.index)));

		const [full, slash, tag, rawAttrs] = m;
		if (TITLE_ALLOWED_TAGS.has(tag.toLowerCase())) {
			let attrs = '';
			if (!slash && rawAttrs) {
				for (const am of rawAttrs.matchAll(/([\w-]+)\s*=\s*"([^"]*)"/g)) {
					if (TITLE_ALLOWED_ATTRS.has(am[1].toLowerCase())) {
						attrs += ` ${am[1].toLowerCase()}="${escapeHtml(am[2])}"`;
					}
				}
			}
			parts.push(`<${slash}${tag.toLowerCase()}${attrs}>`);
		}
		lastIdx = m.index + full.length;
	}

	parts.push(escapeHtml(input.slice(lastIdx)));
	return parts.join('');
}

const HAS_LATEX = /\$\$[\s\S]+?\$\$|\$[^$]+?\$/;
const HAS_MATHML = /<\/?mml:/;

const ENTITY_MAP: Record<string, string> = {
	amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"
};

/* Decode one layer of HTML entities (named + numeric). */
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

/* Décode les entités HTML d'un titre jusqu'à stabilisation (`&lt;sub&gt;` →
 * `<sub>`, `&amp;` → `&`, `&#233;` → `é`). La boucle (bornée) absorbe le
 * double-encodage (`&amp;lt;`). Le markup brut obtenu est ensuite sanitizé ; un
 * `&` de contenu est ré-échappé par `escapeHtml`. */
function decodeHtmlEntities(s: string): string {
	let out = s;
	for (let i = 0; i < 4; i++) {
		const decoded = decodeEntitiesOnce(out);
		if (decoded === out) break;
		out = decoded;
	}
	return out;
}

export function sanitizeTitle(s: string | null | undefined): string {
	if (!s) return '';

	const input = decodeHtmlEntities(s);

	if (HAS_LATEX.test(input)) return renderLatex(input);
	if (HAS_MATHML.test(input) || /<\/?[a-z]/i.test(input)) return sanitizeMathML(input);

	return escapeHtml(input);
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

/** Dérive le statut de détection d'une structure à partir des flags
 * `is_confirmed` (tri-state nullable) et `is_detected` (booléen).
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
