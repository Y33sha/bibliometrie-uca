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
		const { title } = parseMarkdown('# Architecture\n\nContenu', BASE, 'architecture');
		expect(title).toBe('Architecture');
	});

	it('ignore les h1 suivants pour le titre', () => {
		const { title } = parseMarkdown('# Premier\n# Second', BASE, 'test');
		expect(title).toBe('Premier');
	});

	it('renvoie un titre vide si aucun h1', () => {
		const { title } = parseMarkdown('## Pas de h1', BASE, 'test');
		expect(title).toBe('');
	});

	it('gère les fichiers en CRLF', () => {
		const { title, toc } = parseMarkdown('# Titre CRLF\r\n## Section\r\n', BASE, 'test');
		expect(title).toBe('Titre CRLF');
		expect(toc.map((t) => t.anchor)).toEqual(['section']);
	});
});

// ── parseMarkdown / TOC ────────────────────────────────────────

describe('parseMarkdown — table des matières', () => {
	it("collecte les h2 et h3 dans l'ordre", () => {
		const md = '# Titre\n## Section A\n### Sous A\n## Section B';
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc.map((t) => ({ level: t.level, anchor: t.anchor }))).toEqual([
			{ level: 2, anchor: 'section-a' },
			{ level: 3, anchor: 'sous-a' },
			{ level: 2, anchor: 'section-b' }
		]);
	});

	it('ignore les titres dans les blocs de code', () => {
		const md = '# Titre\n```\n## Pas un titre\n```\n## Vrai titre';
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc.map((t) => t.anchor)).toEqual(['vrai-titre']);
	});

	it('ignore les h1 et h4+ dans la TOC', () => {
		const md = '# Titre\n## H2\n#### H4';
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc.map((t) => t.anchor)).toEqual(['h2']);
	});

	it('rend le markdown inline du texte (code, italique, etc.)', () => {
		const { toc } = parseMarkdown('## `extract` : Moissonnage', BASE, 'test');
		expect(toc[0].html).toContain('<code>extract</code>');
		expect(toc[0].html).toContain('Moissonnage');
	});
});

// ── parseMarkdown / ancres custom (<span id="...">) ────────────

describe('parseMarkdown — ancres custom via <span id>', () => {
	it('utilise l\'id du span comme ancre prioritaire', () => {
		const md = '## <span id="extract"></span>`extract` : Moissonnage';
		const { toc, html } = parseMarkdown(md, BASE, 'test');
		expect(toc[0].anchor).toBe('extract');
		expect(html).toContain('<h2 id="extract">');
	});

	it('strippe le <span> du texte affiché dans la TOC', () => {
		const md = '## <span id="x"></span>Texte visible';
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc[0].html).not.toContain('<span');
		expect(toc[0].html).toContain('Texte visible');
	});

	it('strippe le <span> du HTML rendu', () => {
		const md = '## <span id="x"></span>Texte';
		const { html } = parseMarkdown(md, BASE, 'test');
		expect(html).toContain('<h2 id="x">');
		expect(html).not.toContain('<span');
	});

	it('gère un <span> au milieu du heading', () => {
		const md = "## Résumé: <span id='tables'></span>Tables canoniques";
		const { toc, html } = parseMarkdown(md, BASE, 'test');
		expect(toc[0].anchor).toBe('tables');
		expect(html).toContain('<h2 id="tables">');
		expect(html).not.toContain('<span');
	});

	it('tolère apostrophes simples ou doubles', () => {
		const md = "## <span id='abc'></span>Foo";
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc[0].anchor).toBe('abc');
	});
});

// ── parseMarkdown / HTML ───────────────────────────────────────

describe('parseMarkdown — HTML', () => {
	it('ajoute des id sur les titres rendus', () => {
		const { html } = parseMarkdown('## Hello World', BASE, 'test');
		expect(html).toContain('<h2 id="hello-world">');
	});

	it('résout les liens internes vers /docs/', () => {
		const { html } = parseMarkdown('[Voir](pipeline)', BASE, 'test');
		expect(html).toContain('href="/bibliometrie/docs/pipeline"');
	});

	it('résout les liens avec ancre', () => {
		const { html } = parseMarkdown('[Voir](glossaire#ror)', BASE, 'test');
		expect(html).toContain('href="/bibliometrie/docs/glossaire#ror"');
	});

	it('laisse les liens externes intacts', () => {
		const { html } = parseMarkdown('[ROR](https://ror.org/01a8ajp46)', BASE, 'test');
		expect(html).toContain('href="https://ror.org/01a8ajp46"');
	});

	it('préserve les blocs de code mermaid', () => {
		const md = '```mermaid\ngraph TD\nA --> B\n```';
		const { html } = parseMarkdown(md, BASE, 'test');
		expect(html).toContain('language-mermaid');
		expect(html).toContain('graph TD');
	});
});
