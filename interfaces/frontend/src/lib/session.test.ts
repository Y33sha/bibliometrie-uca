import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/paths', () => ({ resolve: (path: string) => '/bibliometrie/' + path }));
vi.mock('#lib/api/index.js', () => ({ auth: {} }));

const { loginUrl, returnPath } = await import('./session.svelte');

const ORIGIN = 'https://exemple.fr';

describe('returnPath', () => {
	it('rend une page du site, avec ses paramètres', () => {
		expect(returnPath('/bibliometrie/persons/12?tab=publications', ORIGIN)).toBe(
			'/bibliometrie/persons/12?tab=publications',
		);
	});

	it('rend la page Statistiques sans redirection', () => {
		expect(returnPath(null, ORIGIN)).toBe('/bibliometrie/stats');
	});

	it.each([
		'https://ailleurs.fr/bibliometrie/stats',
		'//ailleurs.fr/bibliometrie/stats',
		'/\\ailleurs.fr/bibliometrie/stats',
		'/autre-site',
	])('rend la page Statistiques pour %s, hors du site', (redirect) => {
		expect(returnPath(redirect, ORIGIN)).toBe('/bibliometrie/stats');
	});
});

describe('loginUrl', () => {
	it('transmet le chemin et les paramètres de la page courante', () => {
		const url = new URL('https://exemple.fr/bibliometrie/persons/12?tab=publications');
		expect(loginUrl(url)).toBe(
			'/bibliometrie/login?redirect=%2Fbibliometrie%2Fpersons%2F12%3Ftab%3Dpublications',
		);
	});
});
