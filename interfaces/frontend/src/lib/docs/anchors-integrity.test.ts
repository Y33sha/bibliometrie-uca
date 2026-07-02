import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { documentAnchors } from './parser';

/**
 * Contrôle d'intégrité des liens internes de la documentation :
 *
 * - un lien vers un fichier `.md` de la doc (`chemin.md` ou `chemin.md#fragment`)
 *   doit pointer vers un fichier existant ;
 * - son ancre `#fragment` éventuelle, et toute référence glossaire `[[slug]]`,
 *   doivent exister dans le fichier cible.
 *
 * Garde-fou contre les liens cassés qu'aucun autre outil ne détecte (svelte-check
 * ne vérifie que le typage). Les liens hors doc (code source via `.py`/`.svelte`,
 * externes) sont ignorés ; les liens sans extension `.md` (routes de l'UI) ne sont
 * vérifiés que sur leur ancre, pas sur l'existence d'un fichier.
 *
 * Les fiches de `chantiers/` sont indexées comme *cibles* (un lien vers une fiche
 * doit rester valide) mais ne sont pas scannées comme *sources* : leurs propres
 * liens internes ne sont pas contrôlés.
 */

const DOCS_ROOT = path.resolve(fileURLToPath(import.meta.url), '../../../../../../docs');

function listMarkdown(dir: string): string[] {
	const out: string[] = [];
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			out.push(...listMarkdown(full));
		} else if (entry.name.endsWith('.md')) {
			out.push(full);
		}
	}
	return out;
}

const isChantier = (file: string): boolean => file.includes(`${path.sep}chantiers${path.sep}`);

describe('intégrité des ancres de la documentation', () => {
	const files = listMarkdown(DOCS_ROOT);
	const contents = new Map(files.map((f) => [f, readFileSync(f, 'utf8')]));
	const anchors = new Map(files.map((f) => [f, new Set(documentAnchors(contents.get(f)!))]));
	const glossary = anchors.get(path.join(DOCS_ROOT, 'glossaire.md')) ?? new Set<string>();
	const sources = files.filter((f) => !isChantier(f));

	it('découvre bien les fichiers de doc', () => {
		expect(sources.length).toBeGreaterThan(10);
		expect(glossary.size).toBeGreaterThan(0);
	});

	it('toutes les ancres référencées existent dans leur cible', () => {
		const dangling: string[] = [];

		for (const file of sources) {
			const content = contents.get(file)!;
			const rel = path.relative(DOCS_ROOT, file);

			// Références glossaire [[slug]] / [[slug|texte]]
			for (const m of content.matchAll(/\[\[([\w-]+)(?:\|[^\]]+)?\]\]/g)) {
				if (!glossary.has(m[1])) dangling.push(`${rel} : [[${m[1]}]] absent du glossaire`);
			}

			// Liens markdown ](href) / ](href#frag)
			for (const m of content.matchAll(/\]\(([^)]+)\)/g)) {
				const href = m[1];
				if (/^https?:|^mailto:/.test(href)) continue;
				const hash = href.indexOf('#');
				const base = hash < 0 ? href : href.slice(0, hash);
				const frag = hash < 0 ? null : href.slice(hash + 1);

				if (base.endsWith('.md')) {
					// Lien vers un fichier de doc explicite : la cible doit exister,
					// et son ancre éventuelle aussi.
					const target = path.resolve(path.dirname(file), base);
					if (path.relative(DOCS_ROOT, target).startsWith('..')) continue; // hors doc
					const set = anchors.get(target);
					if (!set) {
						dangling.push(`${rel} : fichier cible absent ${path.relative(DOCS_ROOT, target)}`);
					} else if (frag && !set.has(frag)) {
						dangling.push(`${rel} : #${frag} absent de ${path.relative(DOCS_ROOT, target)}`);
					}
				} else if (frag !== null) {
					// Ancre sans fichier explicite : même page (`#frag`) ou route sans
					// `.md` (`../glossaire#frag`). On vérifie l'ancre si la cible est une
					// doc connue, sans juger l'existence d'un fichier (c'est une route).
					const target = base === '' ? file : path.resolve(path.dirname(file), `${base}.md`);
					const set = anchors.get(target);
					if (set && !set.has(frag)) {
						dangling.push(`${rel} : #${frag} absent de ${path.relative(DOCS_ROOT, target)}`);
					}
				}
			}
		}

		expect(dangling).toEqual([]);
	});
});
