import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { documentAnchors } from './parser';

/**
 * Contrôle d'intégrité des ancres de la documentation : toute ancre référencée
 * (lien `…#fragment` vers un `.md` de la doc, ou référence glossaire `[[slug]]`)
 * doit exister dans le fichier cible. Garde-fou contre les liens cassés qu'aucun
 * autre outil ne détecte (svelte-check ne vérifie que le typage).
 *
 * Hors périmètre volontaire : l'existence du fichier cible lui-même (liens vers du
 * code source, routes sans `.md`, fichiers absents) — seules les ancres des docs
 * connues sont vérifiées.
 */

const DOCS_ROOT = path.resolve(fileURLToPath(import.meta.url), '../../../../../../docs');

function listMarkdown(dir: string): string[] {
	const out: string[] = [];
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			if (entry.name === 'chantiers') continue; // fiches internes, non servies
			out.push(...listMarkdown(full));
		} else if (entry.name.endsWith('.md')) {
			out.push(full);
		}
	}
	return out;
}

describe('intégrité des ancres de la documentation', () => {
	const files = listMarkdown(DOCS_ROOT);
	const contents = new Map(files.map((f) => [f, readFileSync(f, 'utf8')]));
	const anchors = new Map(files.map((f) => [f, new Set(documentAnchors(contents.get(f)!))]));
	const glossary = anchors.get(path.join(DOCS_ROOT, 'glossaire.md')) ?? new Set<string>();

	it('découvre bien les fichiers de doc', () => {
		expect(files.length).toBeGreaterThan(10);
		expect(glossary.size).toBeGreaterThan(0);
	});

	it('toutes les ancres référencées existent dans leur cible', () => {
		const dangling: string[] = [];

		for (const [file, content] of contents) {
			const rel = path.relative(DOCS_ROOT, file);

			// Références glossaire [[slug]] / [[slug|texte]]
			for (const m of content.matchAll(/\[\[([\w-]+)(?:\|[^\]]+)?\]\]/g)) {
				if (!glossary.has(m[1])) dangling.push(`${rel} : [[${m[1]}]] absent du glossaire`);
			}

			// Liens markdown avec fragment ](href#frag)
			for (const m of content.matchAll(/\]\(([^)]+)\)/g)) {
				const href = m[1];
				const hash = href.indexOf('#');
				if (hash < 0 || /^https?:|^mailto:/.test(href)) continue;
				const base = href.slice(0, hash);
				const frag = href.slice(hash + 1);
				let target: string;
				if (base === '') target = file;
				else {
					const rer = base.endsWith('.md') ? base : `${base}.md`;
					target = path.resolve(path.dirname(file), rer);
				}
				const set = anchors.get(target);
				if (!set) continue; // cible hors doc (code source, route, fichier absent) : non vérifiée
				if (!set.has(frag)) dangling.push(`${rel} : #${frag} absent de ${path.relative(DOCS_ROOT, target)}`);
			}
		}

		expect(dangling).toEqual([]);
	});
});
