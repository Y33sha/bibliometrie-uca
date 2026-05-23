import { Marked, type RendererObject } from 'marked';
import { resolveDocLink } from './links';

export interface TocEntry {
	level: 2 | 3;
	html: string;
	anchor: string;
}

export interface ParsedDoc {
	html: string;
	toc: TocEntry[];
	title: string;
}

/**
 * Calcule l'ancre d'un titre : lowercase, ponctuation supprimée, espaces → tirets.
 * Doit rester déterministe et identique à la convention utilisée côté backend.
 */
export function makeAnchor(text: string): string {
	return text
		.toLowerCase()
		.replace(/[^\p{L}\p{N}\s_-]/gu, '')
		.replace(/\s+/g, '-')
		.replace(/^-+|-+$/g, '');
}

/**
 * Détecte une ancre custom dans une ligne de heading. Deux conventions reconnues :
 *
 * 1. **Pandoc** : `## Mon titre {#mon-ancre}` à la fin du heading. Convention
 *    préférée pour les .md écrits à la main (concise, lisible).
 * 2. **`<span id="..."></span>`** n'importe où dans le heading. Convention
 *    legacy supportée pour compatibilité avec les .md existants.
 *
 * Si une ancre custom est trouvée, elle remplace l'ancre auto-générée (et le
 * marqueur est strippé du texte affiché).
 */
function extractCustomAnchor(text: string): { anchor: string | null; cleaned: string } {
	const pandoc = /\s*\{#([\w-]+)\}\s*$/.exec(text);
	if (pandoc) {
		const cleaned = text.slice(0, pandoc.index).trim();
		return { anchor: pandoc[1], cleaned };
	}
	const span = /<span\s+id=['"]([^'"]+)['"]\s*>\s*<\/span>\s*/.exec(text);
	if (span) {
		const cleaned = (text.slice(0, span.index) + text.slice(span.index + span[0].length)).trim();
		return { anchor: span[1], cleaned };
	}
	return { anchor: null, cleaned: text };
}

function extractHeadings(content: string): { title: string; toc: TocEntry[] } {
	const inlineMarked = new Marked();
	const toc: TocEntry[] = [];
	let title = '';
	let inCodeBlock = false;
	for (const line of content.split(/\r?\n/)) {
		if (/^```/.test(line)) {
			inCodeBlock = !inCodeBlock;
			continue;
		}
		if (inCodeBlock) continue;
		const m = /^(#{1,3})\s+(.+)$/.exec(line);
		if (!m) continue;
		const level = m[1].length;
		const { anchor: customAnchor, cleaned } = extractCustomAnchor(m[2].trim());
		if (level === 1 && !title) {
			title = cleaned;
		} else if (level === 2 || level === 3) {
			const html = inlineMarked.parseInline(cleaned) as string;
			const anchor = customAnchor ?? makeAnchor(cleaned);
			toc.push({ level, html, anchor });
		}
	}
	return { title, toc };
}

function escapeHtmlAttr(value: string): string {
	return value
		.replace(/&/g, '&amp;')
		.replace(/"/g, '&quot;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

/**
 * Syntaxe glossaire `[[slug]]` / `[[slug|texte affiché]]` — convention MediaWiki/Obsidian.
 *
 * Traitement par **pré-processing** (et non extension marked), parce que le séparateur `|` entre en conflit avec la syntaxe markdown des tables : un `[[apc|APC]]` dans une cellule serait coupé en deux cellules par marked avant qu'une extension inline puisse intervenir. On remplace donc chaque expression par un placeholder (caractères Unicode Private Use Area, invisibles côté markdown comme côté HTML), on parse le markdown, puis on réinjecte le HTML cible.
 *
 * Le `href` reste valide pour dégradation gracieuse (JS désactivé, ctrl+click, lecteurs d'écran). `<GlossaryPopover />` intercepte le clic standard pour afficher le popover.
 */
const GLOSS_PLACEHOLDER_START = '';
const GLOSS_PLACEHOLDER_END = '';
const GLOSS_PLACEHOLDER_RE = new RegExp(
	`${GLOSS_PLACEHOLDER_START}(\\d+)${GLOSS_PLACEHOLDER_END}`,
	'g'
);

interface GlossaryRef {
	slug: string;
	text: string;
}

function extractGlossaryRefs(content: string): { processed: string; refs: GlossaryRef[] } {
	const refs: GlossaryRef[] = [];
	const processed = content.replace(
		/\[\[([\w-]+)(?:\|([^\]]+))?\]\]/g,
		(_match, slug: string, text?: string) => {
			const idx = refs.length;
			refs.push({ slug: slug.trim(), text: (text ?? slug).trim() });
			return `${GLOSS_PLACEHOLDER_START}${idx}${GLOSS_PLACEHOLDER_END}`;
		}
	);
	return { processed, refs };
}

function injectGlossaryRefs(html: string, refs: GlossaryRef[], base: string): string {
	return html.replace(GLOSS_PLACEHOLDER_RE, (_match, idxStr: string) => {
		const ref = refs[parseInt(idxStr, 10)];
		if (!ref) return '';
		const slugAttr = escapeHtmlAttr(ref.slug);
		const textHtml = escapeHtmlAttr(ref.text);
		const hrefAttr = escapeHtmlAttr(`${base}/docs/glossaire#${ref.slug}`);
		return `<a class="gloss" href="${hrefAttr}" data-glossary="${slugAttr}">${textHtml}</a>`;
	});
}

export function parseMarkdown(content: string, base: string, currentSlug: string): ParsedDoc {
	const { processed, refs } = extractGlossaryRefs(content);
	const { title, toc } = extractHeadings(processed);

	const renderer: RendererObject = {
		heading({ tokens, depth }) {
			const inner = this.parser.parseInline(tokens);
			const { anchor: customAnchor, cleaned } = extractCustomAnchor(inner);
			const anchor =
				customAnchor ??
				makeAnchor(tokens.map((t) => ('text' in t ? t.text : '')).join(''));
			return `<h${depth} id="${anchor}">${cleaned}</h${depth}>`;
		},
		link({ href, title: linkTitle, tokens }) {
			const resolved = resolveDocLink(href, base, currentSlug);
			const text = this.parser.parseInline(tokens);
			const titleAttr = linkTitle ? ` title="${escapeHtmlAttr(linkTitle)}"` : '';
			return `<a href="${escapeHtmlAttr(resolved)}"${titleAttr}>${text}</a>`;
		}
	};

	const marked = new Marked({ renderer });
	const rawHtml = marked.parse(processed) as string;
	const html = injectGlossaryRefs(rawHtml, refs, base);
	return { html, toc, title };
}
