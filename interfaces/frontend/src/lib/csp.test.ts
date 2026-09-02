/* Politique de sécurité de contenu des pages.
 *
 * Le dossier de sécurité énonce que l'exécution de scripts se restreint à ceux de
 * l'application, et qu'aucune ressource ne se charge depuis un hôte tiers. Cette garantie tient
 * à la configuration de construction, et à elle seule : le générateur y lit les directives et
 * les écrit dans la page produite, sous forme de balise.
 *
 * L'en-tête que le serveur pose de son côté ne porte que `frame-ancestors`, qu'une balise ne
 * peut pas exprimer. Il ne dit donc rien des ressources, et ne rattrape pas un élargissement
 * fait ici.
 */

import { describe, it, expect } from 'vitest';

import config from '../../svelte.config.js';

/* Valeur attendue de chaque directive. Élargir l'une d'elles est un geste délibéré : elle
 * apparaît dans le dossier de sécurité, qui énonce ce que la page s'autorise.
 *
 * `data:` désigne une ressource embarquée dans la page, non un hôte tiers. `unsafe-inline` sur
 * les styles couvre ceux que le générateur écrit dans le balisage ; un style ne charge ni
 * n'exécute rien. */
const DIRECTIVES_ATTENDUES: Record<string, string[]> = {
	'default-src': ['self'],
	'script-src': ['self'],
	'style-src': ['self', 'unsafe-inline'],
	'img-src': ['self', 'data:'],
	'font-src': ['self', 'data:'],
	'connect-src': ['self'],
	'object-src': ['none'],
	'base-uri': ['self'],
	'form-action': ['self']
};

const csp = config.kit?.csp;
const directives = (csp?.directives ?? {}) as Record<string, string[]>;

describe('politique de sécurité de contenu des pages', () => {
	it('est composée par empreinte des scripts', () => {
		expect(csp?.mode).toBe('hash');
	});

	it('déclare exactement les directives attendues', () => {
		expect(Object.keys(directives).sort()).toEqual(Object.keys(DIRECTIVES_ATTENDUES).sort());
	});

	it.each(Object.entries(DIRECTIVES_ATTENDUES))('%s vaut %s', (directive, attendue) => {
		expect(directives[directive]).toEqual(attendue);
	});

	it("n'ouvre aucune source à un hôte extérieur", () => {
		const sources = Object.values(directives).flat().map(String);
		const exterieurs = sources.filter((s) => /[.:]/.test(s) && s !== 'data:');
		expect(exterieurs, 'Sources nommant un hôte : le dossier de sécurité les énumère.').toEqual(
			[]
		);
	});

	it("n'autorise ni l'exécution de code construit à la volée ni un script en ligne", () => {
		const scripts = directives['script-src'] ?? [];
		expect(scripts).not.toContain('unsafe-eval');
		expect(scripts).not.toContain('unsafe-inline');
	});
});
