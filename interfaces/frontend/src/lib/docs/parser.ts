import { Marked, type RendererObject } from 'marked';
import { resolveDocLink } from './links';

export interface TocEntry {
	level: 2 | 3;
	text: string;
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

function extractHeadings(content: string): { title: string; toc: TocEntry[] } {
	const toc: TocEntry[] = [];
	let title = '';
	let inCodeBlock = false;
	for (const line of content.split('\n')) {
		if (/^```/.test(line)) {
			inCodeBlock = !inCodeBlock;
			continue;
		}
		if (inCodeBlock) continue;
		const m = /^(#{1,3})\s+(.+)$/.exec(line);
		if (!m) continue;
		const level = m[1].length;
		const text = m[2].trim();
		if (level === 1 && !title) {
			title = text;
		} else if (level === 2 || level === 3) {
			toc.push({ level, text, anchor: makeAnchor(text) });
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
			const text = this.parser.parseInline(tokens);
			const plain = tokens.map((t) => ('text' in t ? t.text : '')).join('');
			const anchor = makeAnchor(plain);
			return `<h${depth} id="${anchor}">${text}</h${depth}>`;
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
