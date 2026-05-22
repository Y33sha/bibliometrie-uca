import { describe, it, expect } from 'vitest';
import { makeAnchor, parseMarkdown } from './parser';

const BASE = '/bibliometrie';

// ── makeAnchor ─────────────────────────────────────────────────

describe('makeAnchor', () => {
	it('met en lowercase et remplace les espaces par des tirets', () => {
		expect(makeAnchor('Hello World')).toBe('hello-world');
	});

	it('supprime la ponctuation', () => {
		expect(makeAnchor('Foo, bar !')).toBe('foo-bar');
	});

	it('conserve les accents et chiffres', () => {
		expect(makeAnchor('Données 2024')).toBe('données-2024');
	});

	it('strippe les tirets de bord', () => {
		expect(makeAnchor('  hello  ')).toBe('hello');
	});
});

// ── parseMarkdown / titre ──────────────────────────────────────

describe('parseMarkdown — titre', () => {
	it('extrait le premier h1 comme titre', () => {
		const { title } = parseMarkdown('# Architecture\n\nContenu', BASE);
		expect(title).toBe('Architecture');
	});

	it('ignore les h1 suivants pour le titre', () => {
		const { title } = parseMarkdown('# Premier\n# Second', BASE);
		expect(title).toBe('Premier');
	});

	it('renvoie un titre vide si aucun h1', () => {
		const { title } = parseMarkdown('## Pas de h1', BASE);
		expect(title).toBe('');
	});
});

// ── parseMarkdown / TOC ────────────────────────────────────────

describe('parseMarkdown — table des matières', () => {
	it('collecte les h2 et h3 dans l\'ordre', () => {
		const md = '# Titre\n## Section A\n### Sous A\n## Section B';
		const { toc } = parseMarkdown(md, BASE);
		expect(toc).toEqual([
			{ level: 2, text: 'Section A', anchor: 'section-a' },
			{ level: 3, text: 'Sous A', anchor: 'sous-a' },
			{ level: 2, text: 'Section B', anchor: 'section-b' }
		]);
	});

	it('ignore les titres dans les blocs de code', () => {
		const md = '# Titre\n```\n## Pas un titre\n```\n## Vrai titre';
		const { toc } = parseMarkdown(md, BASE);
		expect(toc).toEqual([{ level: 2, text: 'Vrai titre', anchor: 'vrai-titre' }]);
	});

	it('ignore les h1 et h4+ dans la TOC', () => {
		const md = '# Titre\n## H2\n#### H4';
		const { toc } = parseMarkdown(md, BASE);
		expect(toc).toEqual([{ level: 2, text: 'H2', anchor: 'h2' }]);
	});
});

// ── parseMarkdown / HTML ───────────────────────────────────────

describe('parseMarkdown — HTML', () => {
	it('ajoute des id sur les titres rendus', () => {
		const { html } = parseMarkdown('## Hello World', BASE);
		expect(html).toContain('<h2 id="hello-world">');
	});

	it('résout les liens internes vers /docs/', () => {
		const { html } = parseMarkdown('[Voir](pipeline)', BASE);
		expect(html).toContain('href="/bibliometrie/docs/pipeline"');
	});

	it('résout les liens avec ancre', () => {
		const { html } = parseMarkdown('[Voir](glossaire#ror)', BASE);
		expect(html).toContain('href="/bibliometrie/docs/glossaire#ror"');
	});

	it('laisse les liens externes intacts', () => {
		const { html } = parseMarkdown('[ROR](https://ror.org/01a8ajp46)', BASE);
		expect(html).toContain('href="https://ror.org/01a8ajp46"');
	});

	it('préserve les blocs de code mermaid', () => {
		const md = '```mermaid\ngraph TD\nA --> B\n```';
		const { html } = parseMarkdown(md, BASE);
		expect(html).toContain('language-mermaid');
		expect(html).toContain('graph TD');
	});
});
