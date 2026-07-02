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
 * Calcule l'ancre d'un titre à partir de son texte, selon la convention GitHub :
 * lowercase, ponctuation supprimée (lettres accentuées et underscores conservés),
 * espaces → tirets. Une ancre ainsi dérivée du texte fonctionne à l'identique dans
 * l'UI et sur GitHub, sans marqueur d'ancre explicite dans le Markdown source.
 */
export function makeAnchor(text: string): string {
	return text
		.toLowerCase()
		.replace(/[^\p{L}\p{N}\s_-]/gu, '')
		.replace(/\s+/g, '-')
		.replace(/^-+|-+$/g, '');
}

/**
 * Dédup les ancres dans l'ordre d'apparition, convention GitHub : premier = `foo`, deuxième = `foo-1`, troisième = `foo-2`, … Renvoie une closure qui maintient son propre compteur — appeler `dedupe(baseAnchor)` à chaque heading rencontré.
 */
function makeAnchorDedupe(): (baseAnchor: string) => string {
	const seen = new Map<string, number>();
	return (baseAnchor: string) => {
		const i = seen.get(baseAnchor) ?? 0;
		seen.set(baseAnchor, i + 1);
		return i === 0 ? baseAnchor : `${baseAnchor}-${i}`;
	};
}

/**
 * Ancres effectives d'un document, dans l'ordre du rendu : chaque titre (tous
 * niveaux) produit son slug auto-généré, dédupliqué comme dans le HTML rendu.
 * Sert au contrôle d'intégrité des liens internes de la doc.
 */
export function documentAnchors(content: string): string[] {
	const dedupe = makeAnchorDedupe();
	const anchors: string[] = [];
	let inCodeBlock = false;
	for (const line of content.split(/\r?\n/)) {
		if (/^```/.test(line)) {
			inCodeBlock = !inCodeBlock;
			continue;
		}
		if (inCodeBlock) continue;
		const m = /^#{1,6}\s+(.+)$/.exec(line);
		if (!m) continue;
		anchors.push(dedupe(makeAnchor(m[1].trim())));
	}
	return anchors;
}

function extractHeadings(content: string): { title: string; toc: TocEntry[] } {
	const inlineMarked = new Marked();
	const toc: TocEntry[] = [];
	let title = '';
	let inCodeBlock = false;
	const dedupe = makeAnchorDedupe();
	for (const line of content.split(/\r?\n/)) {
		if (/^```/.test(line)) {
			inCodeBlock = !inCodeBlock;
			continue;
		}
		if (inCodeBlock) continue;
		const m = /^(#{1,3})\s+(.+)$/.exec(line);
		if (!m) continue;
		const level = m[1].length;
		const cleaned = m[2].trim();
		const anchor = dedupe(makeAnchor(cleaned));
		if (level === 1 && !title) {
			title = cleaned;
		} else if (level === 2 || level === 3) {
			const html = inlineMarked.parseInline(cleaned) as string;
			toc.push({ level, html, anchor });
		}
	}
	return { title, toc };
}

/**
 * Réécrit les URLs d'images de la doc :
 *
 * - Liens externes (`http://`, `https://`, `//`) ou absolus (`/`) : inchangés.
 * - Liens relatifs pointant vers `[…/]screenshots/<nom>` (peu importe la profondeur de `../` en amont) : réécrits en `${base}/docs-screenshots/<nom>`. Côté source on garde la convention markdown standard (lisible sur GitHub) ; côté doc déployée, SvelteKit sert les fichiers depuis `static/docs-screenshots/` (copie alimentée par `scripts/copy-doc-screenshots.mjs`).
 * - Tout autre lien relatif : inchangé.
 */
function resolveImageHref(href: string, base: string): string {
	if (/^(https?:|\/\/|\/)/.test(href)) return href;
	const m = /(?:^|\/)screenshots\/([\w.-]+)$/.exec(href);
	if (m) return `${base}/docs-screenshots/${m[1]}`;
	return href;
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
	// Markdown inline rendu APRÈS escape HTML : permet `[[slug|voie *open access*]]`
	// → `<em>open access</em>`, sans rouvrir une injection XSS (les `<` éventuels
	// dans le texte ont déjà été échappés en `&lt;`, que marked passe tel quel).
	const inlineMarked = new Marked();
	return html.replace(GLOSS_PLACEHOLDER_RE, (_match, idxStr: string) => {
		const ref = refs[parseInt(idxStr, 10)];
		if (!ref) return '';
		const slugAttr = escapeHtmlAttr(ref.slug);
		const textHtml = inlineMarked.parseInline(escapeHtmlAttr(ref.text)) as string;
		const hrefAttr = escapeHtmlAttr(`${base}/docs/glossaire#${ref.slug}`);
		return `<a class="gloss" href="${hrefAttr}" data-glossary="${slugAttr}">${textHtml}</a>`;
	});
}

export function parseMarkdown(content: string, base: string, currentSlug: string): ParsedDoc {
	const { processed, refs } = extractGlossaryRefs(content);
	const { title, toc } = extractHeadings(processed);

	// Compteur indépendant pour le rendu HTML, qui suit la même logique de dédup
	// qu'`extractHeadings` (cf. `makeAnchorDedupe`) — convention GitHub `-1`, `-2`, etc.
	// pour les collisions d'ancres auto-générées.
	const renderDedupe = makeAnchorDedupe();

	const renderer: RendererObject = {
		heading({ tokens, depth }) {
			const inner = this.parser.parseInline(tokens);
			const anchor = renderDedupe(makeAnchor(tokens.map((t) => ('text' in t ? t.text : '')).join('')));
			return `<h${depth} id="${anchor}">${inner}</h${depth}>`;
		},
		link({ href, title: linkTitle, tokens }) {
			const resolved = resolveDocLink(href, base, currentSlug);
			const text = this.parser.parseInline(tokens);
			const titleAttr = linkTitle ? ` title="${escapeHtmlAttr(linkTitle)}"` : '';
			// Lien vers le glossaire de la forme `…/docs/glossaire#slug` :
			// émet `class="gloss" data-glossary="slug"` pour que
			// <GlossaryPopover /> intercepte au clic. Si le slug n'existe pas
			// dans la map glossaire, le composant laisse passer le clic et la
			// navigation vers le glossaire se fait normalement.
			const glossaryMatch = /\/docs\/glossaire#([\w-]+)$/.exec(resolved);
			if (glossaryMatch) {
				const slug = glossaryMatch[1];
				return `<a class="gloss" href="${escapeHtmlAttr(resolved)}"${titleAttr} data-glossary="${escapeHtmlAttr(slug)}">${text}</a>`;
			}
			return `<a href="${escapeHtmlAttr(resolved)}"${titleAttr}>${text}</a>`;
		},
		image({ href, title, text }) {
			// Images de doc : source unique sous `docs/screenshots/`, lisible
			// sur GitHub via chemin relatif (`![](../screenshots/foo.png)` depuis
			// une page de section). Côté doc déployée, le script
			// `scripts/copy-doc-screenshots.mjs` copie ces fichiers vers
			// `static/docs-screenshots/`, et on réécrit ici l'URL relative en
			// URL absolue préfixée par `${base}/docs-screenshots/`.
			const resolved = resolveImageHref(href, base);
			const titleAttr = title ? ` title="${escapeHtmlAttr(title)}"` : '';
			return `<img src="${escapeHtmlAttr(resolved)}" alt="${escapeHtmlAttr(text)}"${titleAttr} />`;
		}
	};

	const marked = new Marked({ renderer });
	const rawHtml = marked.parse(processed) as string;
	const html = injectGlossaryRefs(rawHtml, refs, base);
	return { html, toc, title };
}
