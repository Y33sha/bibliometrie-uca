export function esc(s: string | null | undefined): string {
	if (!s) return '';
	const d = document.createElement('div');
	d.textContent = s;
	return d.innerHTML;
}

/* ── sanitizeTitle ─────────────────────────────────────────────
 * Renders publication titles that may contain:
 *  - MathML with mml: namespace prefix  (<mml:msup>, <mml:mi>, …)
 *  - Plain HTML formatting              (<sub>, <sup>, <i>)
 *
 * Strips the mml: prefix so browsers render native MathML,
 * keeps only an allowlist of safe tags/attributes, and escapes
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

export function sanitizeTitle(s: string | null | undefined): string {
	if (!s) return '';

	// Strip mml: namespace prefix from tags
	const input = s.replace(/<(\/?)\s*mml:/g, '<$1');

	const parts: string[] = [];
	let lastIdx = 0;
	const re = /<(\/?)(\w+)(\s[^>]*)?\s*\/?>/g;
	let m;

	while ((m = re.exec(input)) !== null) {
		// Escape text between tags
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
		// Non-allowed tags are silently stripped
		lastIdx = m.index + full.length;
	}

	parts.push(escapeHtml(input.slice(lastIdx)));
	return parts.join('');
}

export function titleCase(s: string | null | undefined): string {
	if (!s) return '';
	return s
		.split(/(\s+|[-\u2010\u2011\u2012\u2013\u2014])/g)
		.map((w) => (/^[\s\-\u2010-\u2014]+$/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()))
		.join('');
}

export function formatDate(d: string | null | undefined): string {
	if (!d) return '';
	const parts = d.split('-');
	if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
	return d;
}
