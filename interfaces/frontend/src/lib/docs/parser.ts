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
 * Détecte un `<span id="..."></span>` dans une ligne de heading.
 * Si présent : l'id devient l'ancre du heading et le span est strippé du texte.
 * Permet aux .md de définir des ancres courtes et stables, déconnectées du texte.
 */
function extractCustomAnchor(text: string): { anchor: string | null; cleaned: string } {
	const m = /<span\s+id=['"]([^'"]+)['"]\s*>\s*<\/span>\s*/.exec(text);
	if (!m) return { anchor: null, cleaned: text };
	const cleaned = (text.slice(0, m.index) + text.slice(m.index + m[0].length)).trim();
	return { anchor: m[1], cleaned };
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

export function parseMarkdown(content: string, base: string): ParsedDoc {
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
			const resolved = resolveDocLink(href, base);
			const text = this.parser.parseInline(tokens);
			const titleAttr = linkTitle ? ` title="${escapeHtmlAttr(linkTitle)}"` : '';
			return `<a href="${escapeHtmlAttr(resolved)}"${titleAttr}>${text}</a>`;
		}
	};

	const marked = new Marked({ renderer });
	const html = marked.parse(content) as string;
	return { html, toc, title };
}
