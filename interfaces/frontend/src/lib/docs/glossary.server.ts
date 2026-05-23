/**
 * Construit, au build SvelteKit, un index `slug → { term, html }` à partir de `docs/glossaire.md`.
 *
 * Format attendu du glossaire : une liste plate d'entrées au niveau `h2`, chacune avec une ancre Pandoc explicite :
 *
 * ```markdown
 * # Glossaire
 *
 * ## DOI {#doi}
 * *Digital Object Identifier*. Identifiant unique…
 *
 * ## Types de document {#doc-types}
 * | Type | Description |
 * |------|-------------|
 * | …    | …           |
 * ```
 *
 * Le contenu de chaque entrée s'étend jusqu'au prochain `## ` (ou la fin du fichier). Les entrées sans ancre Pandoc sont ignorées (politique pas-d'autoextraction, cf. fiche chantier).
 *
 * L'index est utilisé par `<GlossaryPopover />` pour afficher la définition d'un terme au clic sur un lien `[[slug]]` ailleurs dans la doc.
 */

import { parseMarkdown } from './parser';
import { readDocFile } from './filesystem.server';

export interface GlossaryEntry {
	term: string;
	html: string;
}

let cache: { base: string; entries: Record<string, GlossaryEntry> } | null = null;

const HEADING_RE = /^##\s+(.+?)\s+\{#([\w-]+)\}\s*$/m;

export function buildGlossary(base: string): Record<string, GlossaryEntry> {
	if (cache && cache.base === base) return cache.entries;

	const content = readDocFile('glossaire');
	const entries: Record<string, GlossaryEntry> = {};

	// Sépare le contenu en blocs commençant par "## " en début de ligne.
	// Le premier bloc avant le premier `##` (typiquement le h1 + intro) est ignoré.
	const blocks = content.split(/(?=^##\s)/m);
	for (const block of blocks) {
		const firstLineEnd = block.indexOf('\n');
		const firstLine = firstLineEnd >= 0 ? block.slice(0, firstLineEnd) : block;
		const m = HEADING_RE.exec(firstLine);
		if (!m) continue;
		const term = m[1].trim();
		const slug = m[2].trim();
		const body = firstLineEnd >= 0 ? block.slice(firstLineEnd + 1).trim() : '';
		// `parseMarkdown` renvoie aussi un titre et une TOC mais on n'en a pas l'usage ici —
		// seul le HTML rendu compte pour le popover.
		const { html } = parseMarkdown(body, base, 'glossaire');
		entries[slug] = { term, html };
	}

	cache = { base, entries };
	return entries;
}
