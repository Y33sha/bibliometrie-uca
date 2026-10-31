/* Hôtes que l'interface peut désigner dans un lien.
 *
 * Toute adresse affichée porte un hôte écrit dans le code, sauf les copies ouvertes d'une
 * publication, hébergées sur des centaines de sites.
 * Deux vérifications le tiennent : les URL littérales des sources visent un hôte de la liste
 * ci-dessous, et tout attribut `href` d'un gabarit passe par une fonction de composition
 * plutôt que par une valeur reçue de l'API. Un `href` tiré d'une prop se vérifie là où chaque
 * page passe la prop au composant.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/* Hôtes que l'interface donne à voir. Y ajouter une entrée est un geste délibéré. */
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
	// confronte à cet hôte avant de la servir (`infrastructure/read_models/doaj_links.py`).
	'doaj.org',
	// Rapport de participation d'un membre Crossref, depuis la liste des éditeurs.
	'www.crossref.org',
	// Notice d'un ISSN lié à une revue sans y être rattaché, depuis la fiche de la revue.
	'portal.issn.org'
]);

/* Expressions admises dans un attribut `href`. Les fonctions de composition écrivent l'hôte ;
 * les valeurs internes désignent une route de l'application. */
const COMPOSITION =
	/^(halPersonUrl|halUrl|halCollectionUrl|rorFullUrl|crossrefMemberUrl|issnPortalUrl|exportCsvUrl|relHref)\(/;
const INTERNE = /^(pubsUrl|statsUrl)$/;
/* `resolve` compose un chemin de l'application sous le préfixe de déploiement, `withBase` un
 * chemin de l'API ; `loginUrl` y ajoute la page de retour après connexion. */
const ROUTE = /^(resolve|withBase|loginUrl)\(/;
const TABLE_IDENTIFIANTS = /^(EXT_META\[|meta\.url\()/;
/* Fiche DOAJ servie par l'API, dont l'hôte est vérifié côté serveur. Liens vers le portail d'une
 * source, composés par l'API : l'hôte y est écrit dans le code et l'identifiant encodé
 * (`domain/sources/registry.py`, `source_record_url`). */
const VERIFIE_COTE_SERVEUR = /^[a-z]+\.(doaj_url|record_url|record_urls(\.[a-z]+)?)$/;
/* Copie ouverte d'une publication, et bouton d'accès qui y mène à défaut du DOI : l'hôte vient
 * des données, le serveur vérifie seulement le schéma `http` ou `https`
 * (`domain/publications/access.py`). */
const COPIE_OUVERTE = /^(copy\.url|accessUrl)$/;
const REGLES = [COMPOSITION, INTERNE, ROUTE, TABLE_IDENTIFIANTS, VERIFIE_COTE_SERVEUR, COPIE_OUVERTE];

const URL_LITTERALE = /https?:\/\/([A-Za-z0-9._-]+)/g;
// Attribut `href`, sous sa forme longue `href={…}` ou raccourcie `{href}`.
const LIAISON_HREF = /\shref=\{([^}]*)\}|\s\{(href)\}/g;

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

/** Texte entre l'accolade ouvrante d'indice `debut` et l'accolade fermante qui lui répond. */
function blocAccolades(texte: string, debut: number): string {
	let profondeur = 0;
	for (let i = debut; i < texte.length; i++) {
		if (texte[i] === '{') profondeur++;
		else if (texte[i] === '}' && --profondeur === 0) return texte.slice(debut + 1, i);
	}
	return '';
}

/** Props d'un composant, lues dans la déstructuration de `$props()`. Une page de route reçoit les siennes de son chargement : elle n'en a aucune à vérifier chez un appelant. */
function propsDe(chemin: string, contenu: string): Set<string> {
	if (basename(chemin).startsWith('+')) return new Set();
	const fin = contenu.indexOf('$props()');
	const debut = fin < 0 ? -1 : contenu.lastIndexOf('let {', fin);
	if (debut < 0) return new Set();
	// Les valeurs par défaut peuvent contenir des virgules : parenthèses, crochets, accolades et chaînes sont retirés.
	let bloc = blocAccolades(contenu, debut + 4);
	let avant;
	do {
		avant = bloc;
		bloc = bloc.replace(/\([^()]*\)|\[[^[\]]*\]|\{[^{}]*\}|'[^']*'|"[^"]*"/g, '');
	} while (bloc !== avant);
	return new Set(
		bloc
			.split(',')
			.map((p) => p.trim().match(/^(\w+)/)?.[1])
			.filter((nom): nom is string => !!nom),
	);
}

/** Texte des balises ouvrantes de `composant` dans `contenu`, attributs compris. */
function balises(contenu: string, composant: string): string[] {
	const trouvees: string[] = [];
	for (const m of contenu.matchAll(new RegExp(`<${composant}[\\s/>]`, 'g'))) {
		let profondeur = 0;
		for (let i = m.index; i < contenu.length; i++) {
			if (contenu[i] === '{') profondeur++;
			else if (contenu[i] === '}') profondeur--;
			else if (contenu[i] === '>' && profondeur === 0) {
				trouvees.push(contenu.slice(m.index, i));
				break;
			}
		}
	}
	return trouvees;
}

/** Expressions passées à la prop `prop` dans une balise, sous la forme `prop={…}` ou `{prop}`. */
function valeursProp(balise: string, prop: string): string[] {
	const valeurs: string[] = [];
	for (const m of balise.matchAll(new RegExp(`\\s${prop}=\\{`, 'g'))) {
		valeurs.push(blocAccolades(balise, m.index + m[0].length - 1));
	}
	if (new RegExp(`\\s\\{${prop}\\}`).test(balise)) valeurs.push(prop);
	return valeurs;
}

/** Vrai si l'expression passe par une règle ; une condition ternaire, si chacune de ses branches passe. */
function admise(expression: string): boolean {
	const e = expression.trim();
	if (e === 'undefined' || e === 'null') return true;
	if (REGLES.some((regle) => regle.test(e))) return true;
	const ternaire = /^[^?]+\?([\s\S]+):([\s\S]+)$/.exec(e);
	return !!ternaire && admise(ternaire[1]) && admise(ternaire[2]);
}

/** Expression qui définit la constante `nom` du fichier (`const nom = …` ou `const nom = $derived(…)`), ou `null`. */
function definitionLocale(contenu: string, nom: string): string | null {
	const m = new RegExp(`const\\s+${nom}\\s*=\\s*(\\$derived\\()?`).exec(contenu);
	if (!m) return null;
	const debut = m.index + m[0].length;
	if (!m[1]) return contenu.slice(debut, contenu.indexOf(';', debut));
	let profondeur = 1;
	for (let i = debut; i < contenu.length; i++) {
		if (contenu[i] === '(') profondeur++;
		else if (contenu[i] === ')' && --profondeur === 0) return contenu.slice(debut, i);
	}
	return null;
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
			"Hôtes écrits dans l'interface sans figurer à la liste. Les y inscrire est un geste délibéré."
		).toEqual([]);
	});

	it('tout attribut href passe par une fonction de composition', () => {
		const fichiers = fichiersSous(SRC, ['.svelte']).map((chemin) => {
			const contenu = readFileSync(chemin, 'utf8');
			return { chemin, contenu, composant: basename(chemin, '.svelte'), props: propsDe(chemin, contenu) };
		});
		const directs: string[] = [];
		const transmises = new Set<string>();

		// Une expression qui part d'une prop du composant est vérifiée là où chaque page la lui passe ; une constante locale, à sa définition.
		function verifier(fichier: (typeof fichiers)[number], expression: string, lieu: string) {
			const e = expression.trim();
			if (admise(e)) return;
			const racine = /^([A-Za-z_$][\w$]*)/.exec(e)?.[1];
			const definition = /^[A-Za-z_$][\w$]*$/.test(e) ? definitionLocale(fichier.contenu, e) : null;
			if (racine && fichier.props.has(racine)) transmettre(fichier.composant, racine);
			else if (definition !== null) verifier(fichier, definition, lieu);
			else directs.push(`${e} (${lieu}, ${fichier.chemin})`);
		}

		function transmettre(composant: string, prop: string) {
			const cle = `${composant}.${prop}`;
			if (transmises.has(cle)) return;
			transmises.add(cle);
			for (const appelant of fichiers) {
				for (const balise of balises(appelant.contenu, composant)) {
					for (const valeur of valeursProp(balise, prop)) verifier(appelant, valeur, cle);
				}
			}
		}

		for (const fichier of fichiers) {
			for (const m of fichier.contenu.matchAll(LIAISON_HREF)) verifier(fichier, m[1] ?? m[2], 'href');
		}
		expect(
			directs,
			"Un `href` reçoit une valeur qui ne passe par aucune fonction de composition : l'hôte affiché viendrait alors des données."
		).toEqual([]);
	});
});

describe('suivi des liens transmis par une prop', () => {
	it('lit les props malgré les virgules des valeurs par défaut', () => {
		const contenu = "let { a, b = $bindable([1, 2]), c = { k: 1, l: 2 }, d = 'x, y' }: P = $props();";
		expect([...propsDe('Composant.svelte', contenu)]).toEqual(['a', 'b', 'c', 'd']);
	});

	it("ne prête aucune prop à une page de route, qui reçoit les siennes de son chargement", () => {
		expect(propsDe('+page.svelte', 'let { data } = $props();').size).toBe(0);
	});

	it('trouve la valeur passée à une prop, sous sa forme longue ou raccourcie', () => {
		const contenu = '<Liens ids={[1, 2]} onclick={() => x > 1} urls={p.record_urls} />\n<Liens {urls} />';
		const valeurs = balises(contenu, 'Liens').flatMap((b) => valeursProp(b, 'urls'));
		expect(valeurs).toEqual(['p.record_urls', 'urls']);
	});

	it('admet une condition ternaire seulement si chacune de ses branches passe', () => {
		expect(admise("lab ? withBase('/api/export.csv') : undefined")).toBe(true);
		expect(admise("lab ? row.url : withBase('/api/export.csv')")).toBe(false);
		expect(admise('row.url')).toBe(false);
	});

	it("lit la définition d'une constante locale", () => {
		expect(definitionLocale("const lien = $derived(withBase('/a'));", 'lien')).toBe("withBase('/a')");
		expect(definitionLocale("const lien = row.url;", 'lien')).toBe('row.url');
	});
});
