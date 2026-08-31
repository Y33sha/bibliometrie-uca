/* Hôtes que l'interface peut désigner dans un lien.
 *
 * Le dossier de sécurité énonce que toute adresse affichée porte un hôte écrit dans le code.
 * Deux vérifications la tiennent : les URL littérales des sources visent un hôte de la liste
 * ci-dessous, et tout attribut `href` d'un gabarit passe par une fonction de composition
 * plutôt que par une valeur reçue de l'API.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';

const SRC = new URL('..', import.meta.url).pathname;

/* Hôtes que l'interface donne à voir. Y ajouter une entrée est un geste délibéré : elle
 * apparaît alors dans le dossier de sécurité, qui les énumère. */
const HOTES_AFFICHABLES = new Set([
	'hal.science',
	'theses.hal.science',
	'dumas.ccsd.cnrs.fr',
	'doi.org',
	'ror.org',
	'orcid.org',
	'www.idref.fr',
	'theses.fr',
	'openalex.org',
	'scanr.enseignementsup-recherche.gouv.fr',
	'www.webofscience.com',
	'arxiv.org',
	'pubmed.ncbi.nlm.nih.gov',
	'www.ncbi.nlm.nih.gov',
	// Fiche de revue en libre accès. Seule adresse qui vienne des données : le serveur la
	// confronte à cet hôte avant de la servir (`infrastructure/sources/doaj/urls.py`).
	'doaj.org'
]);

/* Expressions admises dans un attribut `href`. Les fonctions de composition écrivent l'hôte ;
 * les valeurs internes désignent une route de l'application. */
const COMPOSITION = /^(halDocUrl|halUrl|halCollectionUrl|scanrPubUrl|rorFullUrl|sourceExternalUrl|exportCsvUrl|relHref)\(/;
const INTERNE = /^(pubsUrl|statsUrl|accessUrl)$/;
const TABLE_IDENTIFIANTS = /^(EXT_META\[|meta\.url\()/;
/* Fiche DOAJ servie par l'API, dont l'hôte est vérifié côté serveur. */
const VERIFIE_COTE_SERVEUR = /^[a-z]+\.doaj_url$/;

const URL_LITTERALE = /https?:\/\/([A-Za-z0-9._-]+)/g;
const LIAISON_HREF = /href=\{([^}]*)\}/g;

const IGNORES = new Set(['api', 'node_modules']);

function fichiersSous(racine: string, suffixes: string[]): string[] {
	const trouves: string[] = [];
	for (const entree of readdirSync(racine)) {
		if (IGNORES.has(entree)) continue;
		const chemin = join(racine, entree);
		if (statSync(chemin).isDirectory()) trouves.push(...fichiersSous(chemin, suffixes));
		else if (suffixes.some((s) => entree.endsWith(s))) trouves.push(chemin);
	}
	return trouves;
}

describe('hôtes des liens affichés', () => {
	it('toute URL littérale vise un hôte déclaré', () => {
		const inconnus = new Map<string, string>();
		for (const fichier of fichiersSous(SRC, ['.ts', '.svelte'])) {
			if (fichier.endsWith('.test.ts')) continue;
			for (const ligne of readFileSync(fichier, 'utf8').split('\n')) {
				// Un espace de noms XML et un lien de commentaire ne deviennent pas une adresse affichée.
				if (ligne.includes('xmlns') || /^\s*(\*|\/\/)/.test(ligne)) continue;
				for (const [, hote] of ligne.matchAll(URL_LITTERALE)) {
					if (!HOTES_AFFICHABLES.has(hote)) inconnus.set(hote, fichier);
				}
			}
		}
		expect(
			[...inconnus].map(([hote, fichier]) => `${hote} (${fichier})`),
			"Hôtes écrits dans l'interface sans figurer à la liste. Les y inscrire suppose de mettre à jour le dossier de sécurité, qui les énumère."
		).toEqual([]);
	});

	it('tout attribut href passe par une fonction de composition', () => {
		const directs: string[] = [];
		for (const fichier of fichiersSous(SRC, ['.svelte'])) {
			const contenu = readFileSync(fichier, 'utf8');
			for (const [, expression] of contenu.matchAll(LIAISON_HREF)) {
				const e = expression.trim();
				if (e.startsWith('{base}') || e.includes('base}')) continue;
				if (COMPOSITION.test(e) || INTERNE.test(e)) continue;
				if (TABLE_IDENTIFIANTS.test(e) || VERIFIE_COTE_SERVEUR.test(e)) continue;
				directs.push(`${e} (${fichier})`);
			}
		}
		expect(
			directs,
			"Un `href` reçoit une valeur qui ne passe par aucune fonction de composition : l'hôte affiché viendrait alors des données."
		).toEqual([]);
	});
});
