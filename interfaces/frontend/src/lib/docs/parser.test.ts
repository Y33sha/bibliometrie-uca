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

// ── parseMarkdown / ancres = slug auto (pas de marqueur custom) ─

describe('parseMarkdown — ancres dérivées du texte (parité GitHub)', () => {
	it('dérive toujours l\'ancre du texte du titre', () => {
		const { toc, html } = parseMarkdown('## Mon titre', BASE, 'test');
		expect(toc[0].anchor).toBe('mon-titre');
		expect(html).toContain('<h2 id="mon-titre">');
	});

	it('traite un marqueur {#…} comme du texte littéral, sans ancre custom', () => {
		// Comme sur GitHub : `{#slug}` n'est pas une syntaxe d'ancre, il est
		// rendu tel quel et compte dans le slug auto-généré.
		const { toc, html } = parseMarkdown('## Foo {#bar}', BASE, 'test');
		expect(toc[0].anchor).toBe('foo-bar');
		expect(html).toContain('<h2 id="foo-bar">');
		expect(html).toContain('{#bar}');
	});
});

// ── parseMarkdown / dédup d'ancres pour titres homonymes ───────

describe('parseMarkdown — dédup ancres', () => {
	it('suffixe -1, -2, … les doublons (convention GitHub)', () => {
		const md = '## Hello\n## Hello\n## Hello';
		const { toc, html } = parseMarkdown(md, BASE, 'test');
		expect(toc.map((t) => t.anchor)).toEqual(['hello', 'hello-1', 'hello-2']);
		expect(html).toContain('<h2 id="hello">');
		expect(html).toContain('<h2 id="hello-1">');
		expect(html).toContain('<h2 id="hello-2">');
	});

	it("dédup les sous-titres répétés sous deux sections différentes (cas option A / option B)", () => {
		const md =
			'## Option A\n### Avec Docker\n### Sans Docker\n## Option B\n### Avec Docker\n### Sans Docker';
		const { toc } = parseMarkdown(md, BASE, 'test');
		expect(toc.map((t) => t.anchor)).toEqual([
			'option-a',
			'avec-docker',
			'sans-docker',
			'option-b',
			'avec-docker-1',
			'sans-docker-1'
		]);
	});

});

// ── parseMarkdown / syntaxe glossaire [[…]] ────────────────────

describe('parseMarkdown — syntaxe glossaire [[slug]] / [[slug|texte]]', () => {
	it('rend [[slug]] en lien gloss vers glossaire#slug avec slug comme texte', () => {
		const { html } = parseMarkdown('Le [[doi]] est un identifiant.', BASE, 'test');
		expect(html).toContain('class="gloss"');
		expect(html).toContain('data-glossary="doi"');
		expect(html).toContain('href="/bibliometrie/docs/glossaire#doi"');
		expect(html).toContain('>doi</a>');
	});

	it('rend [[slug|texte]] avec texte affiché distinct du slug', () => {
		const { html } = parseMarkdown('Voir [[doc-types|type de document]] ici.', BASE, 'test');
		expect(html).toContain('data-glossary="doc-types"');
		expect(html).toContain('href="/bibliometrie/docs/glossaire#doc-types"');
		expect(html).toContain('>type de document</a>');
	});

	it('ne match pas les slugs avec espaces ou caractères spéciaux', () => {
		const { html } = parseMarkdown('Pas un slug : [[un terme]].', BASE, 'test');
		expect(html).not.toContain('class="gloss"');
	});

	it('échappe le texte affiché contre les injections HTML', () => {
		const { html } = parseMarkdown('[[doi|<script>x</script>]]', BASE, 'test');
		expect(html).not.toContain('<script>');
		expect(html).toContain('&lt;script');
	});

	it('rend le markdown inline dans le texte affiché (italique, gras, code)', () => {
		const { html } = parseMarkdown('[[oa_status|voie *open access*]]', BASE, 'test');
		expect(html).toContain('data-glossary="oa_status"');
		expect(html).toContain('<em>open access</em>');
		expect(html).not.toContain('*open access*');
	});

	it("survit au pipe dans une cellule de tableau (régression bug 11-enrich.md ligne 8)", () => {
		const md = '| Col1 | Col2 |\n|---|---|\n| Montant [[apc|APC]] payé | autre |';
		const { html } = parseMarkdown(md, BASE, 'test');
		// La cellule ne doit pas être coupée par le `|` interne du token glossaire.
		expect(html).toContain('Montant');
		expect(html).toContain('data-glossary="apc"');
		expect(html).toContain('>APC</a>');
		expect(html).toContain('payé');
		// La 2e colonne doit rester sur sa propre cellule.
		expect(html).toContain('autre');
	});
});

// ── parseMarkdown / liens glossaire en syntaxe markdown standard ───

describe('parseMarkdown — liens markdown `[…](glossaire#slug)` traités comme liens glossaire', () => {
	it('depuis une page racine : `[texte](glossaire#slug)` émet data-glossary', () => {
		const { html } = parseMarkdown('Voir [le DOI](glossaire#doi)', BASE, 'test');
		expect(html).toContain('class="gloss"');
		expect(html).toContain('data-glossary="doi"');
		expect(html).toContain('href="/bibliometrie/docs/glossaire#doi"');
		expect(html).toContain('>le DOI</a>');
	});

	it('depuis une page de section : `[texte](../glossaire#slug)` émet data-glossary', () => {
		const { html } = parseMarkdown('Voir [APC](../glossaire#apc)', BASE, 'sources/hal');
		expect(html).toContain('data-glossary="apc"');
		expect(html).toContain('href="/bibliometrie/docs/glossaire#apc"');
	});

	it('un lien vers le glossaire sans ancre ne déclenche pas le popover', () => {
		const { html } = parseMarkdown('Voir [le glossaire](glossaire)', BASE, 'test');
		expect(html).not.toContain('data-glossary');
		expect(html).toContain('href="/bibliometrie/docs/glossaire"');
	});

	it('les autres liens internes ne sont pas affectés', () => {
		const { html } = parseMarkdown('Voir [pipeline](pipeline)', BASE, 'test');
		expect(html).not.toContain('data-glossary');
		expect(html).not.toContain('class="gloss"');
	});

	it("le texte d'un lien glossaire markdown rend l'italique inline", () => {
		const { html } = parseMarkdown(
			'Voir [voie *open access*](glossaire#oa_status)',
			BASE,
			'test'
		);
		expect(html).toContain('data-glossary="oa_status"');
		expect(html).toContain('<em>open access</em>');
	});
});

// ── parseMarkdown / images de doc ──────────────────────────────

describe('parseMarkdown — images de doc (réécriture vers /docs-screenshots/ et /docs-graphs/)', () => {
	it('réécrit `![](../img/screenshots/foo.png)` depuis une page de section', () => {
		const { html } = parseMarkdown(
			'![Stats](../img/screenshots/stats_oa_status.png)',
			BASE,
			'guide-utilisateur/pages-publiques'
		);
		expect(html).toContain('<img src="/bibliometrie/docs-screenshots/stats_oa_status.png"');
		expect(html).toContain('alt="Stats"');
	});

	it('réécrit `![](screenshots/foo.png)` depuis une page racine', () => {
		const { html } = parseMarkdown('![](screenshots/foo.png)', BASE, 'test');
		expect(html).toContain('<img src="/bibliometrie/docs-screenshots/foo.png"');
	});

	it('réécrit `![](../img/graphs/foo.png)` vers /docs-graphs/', () => {
		const { html } = parseMarkdown('![G](../img/graphs/reconciliation.png)', BASE, 'pipeline/publications');
		expect(html).toContain('<img src="/bibliometrie/docs-graphs/reconciliation.png"');
	});

	it('laisse intacts les liens absolus et externes', () => {
		const ext = parseMarkdown('![ext](https://example.com/x.png)', BASE, 'test').html;
		expect(ext).toContain('src="https://example.com/x.png"');
		const abs = parseMarkdown('![abs](/static/x.png)', BASE, 'test').html;
		expect(abs).toContain('src="/static/x.png"');
	});

	it('laisse intacts les chemins relatifs hors `screenshots/` et `graphs/`', () => {
		const { html } = parseMarkdown('![other](../assets/icon.svg)', BASE, 'sources/hal');
		expect(html).toContain('src="../assets/icon.svg"');
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
