import { Marked, type RendererObject, type TokenizerAndRendererExtension } from 'marked';
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
 * Extension marked inline pour la syntaxe glossaire `[[slug]]` / `[[slug|texte affiché]]`.
 *
 * Génère un `<a class="gloss" data-glossary="slug" href="…glossaire#slug">texte</a>`. Le `href` reste valide pour dégradation gracieuse (JS désactivé, ctrl+click, lecteurs d'écran) ; le composant `<GlossaryPopover />` intercepte le clic standard pour afficher le popover.
 *
 * Convention : `[[slug]]` quand texte = slug, `[[slug|texte]]` sinon (style MediaWiki / Obsidian). Le slug doit être [\w-]+.
 */
function glossaryExtension(base: string): TokenizerAndRendererExtension {
	return {
		name: 'glossary',
		level: 'inline',
		start(src: string): number | undefined {
			const idx = src.indexOf('[[');
			return idx >= 0 ? idx : undefined;
		},
		tokenizer(src: string) {
			const rule = /^\[\[([\w-]+)(?:\|([^\]]+))?\]\]/;
			const match = rule.exec(src);
			if (!match) return undefined;
			const slug = match[1].trim();
			const text = (match[2] ?? match[1]).trim();
			return {
				type: 'glossary',
				raw: match[0],
				slug,
				text
			};
		},
		renderer(token) {
			const t = token as unknown as { slug: string; text: string };
			const slugAttr = escapeHtmlAttr(t.slug);
			const textHtml = escapeHtmlAttr(t.text);
			const hrefAttr = escapeHtmlAttr(`${base}/docs/glossaire#${t.slug}`);
			return `<a class="gloss" href="${hrefAttr}" data-glossary="${slugAttr}">${textHtml}</a>`;
		}
	};
}

export function parseMarkdown(content: string, base: string, currentSlug: string): ParsedDoc {
	const { title, toc } = extractHeadings(content);

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

	const marked = new Marked({ renderer, extensions: [glossaryExtension(base)] });
	const html = marked.parse(content) as string;
	return { html, toc, title };
}
