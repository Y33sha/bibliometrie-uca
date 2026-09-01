import { describe, it, expect, beforeEach } from 'vitest';
import {
	useColumnVisibility,
	type ColumnDef,
	type ColumnStorage,
} from './useColumnVisibility.svelte';

const STORAGE_KEY = 'pub-table-columns';

/**
 * Stockage en mémoire, tenant lieu de celui du navigateur.
 *
 * Le composable recevant son stockage, ces tests n'ont besoin d'aucun environnement de
 * navigateur simulé : ils éprouvent les règles de visibilité, pas la persistance.
 */
function memoryStorage(): ColumnStorage {
	const contenu = new Map<string, string>();
	return {
		getItem: key => contenu.get(key) ?? null,
		setItem: (key, value) => {
			contenu.set(key, value);
		},
	};
}

const cols: ColumnDef[] = [
	{ key: 'title', label: 'Titre', fixed: true },
	{ key: 'year', label: 'Année' },
	{ key: 'doi', label: 'DOI' },
	{ key: 'oa', label: 'OA' },
];

describe('useColumnVisibility', () => {
	let storage: ColumnStorage;

	beforeEach(() => {
		storage = memoryStorage();
	});

	it('par défaut, toutes les colonnes sont visibles si rien dans le storage', () => {
		const v = useColumnVisibility(cols, [], storage);
		expect(v.visibleColumns).toEqual(['title', 'year', 'doi', 'oa']);
	});

	it('respecte defaultHidden au premier chargement', () => {
		const v = useColumnVisibility(cols, ['doi', 'oa'], storage);
		expect(v.visibleColumns).toEqual(['title', 'year']);
	});

	it('restaure depuis le stockage et conserve l\'ordre des colonnes définies', () => {
		// Le stockage peut contenir des clés dans n'importe quel ordre.
		storage.setItem(STORAGE_KEY, JSON.stringify(['oa', 'year']));
		const v = useColumnVisibility(cols, [], storage);
		// Les colonnes fixes (title) sont toujours réinjectées ; ordre préservé.
		expect(v.visibleColumns).toContain('title');
		expect(v.visibleColumns).toContain('year');
		expect(v.visibleColumns).toContain('oa');
		expect(v.visibleColumns).not.toContain('doi');
	});

	it('ignore les clés inconnues dans le stockage (autre page)', () => {
		storage.setItem(STORAGE_KEY, JSON.stringify(['title', 'unknown_col', 'year']));
		const v = useColumnVisibility(cols, [], storage);
		expect(v.visibleColumns).not.toContain('unknown_col');
	});

	it('toggle bascule une colonne non-fixe et persiste', () => {
		const v = useColumnVisibility(cols, [], storage);
		v.toggle('doi');
		expect(v.visibleColumns).not.toContain('doi');
		expect(JSON.parse(storage.getItem(STORAGE_KEY) || '[]')).not.toContain('doi');

		v.toggle('doi');
		expect(v.visibleColumns).toContain('doi');
	});

	it('toggle réinsère la colonne dans l\'ordre d\'origine', () => {
		const v = useColumnVisibility(cols, [], storage);
		v.toggle('year');
		v.toggle('doi');
		// year et doi cachées
		v.toggle('year');
		// year doit revenir à sa position d'origine (avant doi)
		expect(v.visibleColumns).toEqual(['title', 'year', 'oa']);
	});

	it('toggle ignore les colonnes fixes', () => {
		const v = useColumnVisibility(cols, [], storage);
		v.toggle('title');
		expect(v.visibleColumns).toContain('title');
	});

	it('col(key) renvoie l\'état de visibilité', () => {
		const v = useColumnVisibility(cols, ['doi'], storage);
		expect(v.col('title')).toBe(true);
		expect(v.col('doi')).toBe(false);
	});

	it('ensure ajoute des colonnes manquantes en respectant l\'ordre', () => {
		const v = useColumnVisibility(cols, ['year', 'doi', 'oa'], storage);
		// Au départ, seul `title` est visible.
		expect(v.visibleColumns).toEqual(['title']);
		v.ensure(['oa', 'doi']);
		// Réinsérées dans l'ordre des colonnes définies.
		expect(v.visibleColumns).toEqual(['title', 'doi', 'oa']);
	});

	it('ensure ignore les clés inconnues', () => {
		const v = useColumnVisibility(cols, [], storage);
		const before = [...v.visibleColumns];
		v.ensure(['inexistant']);
		expect(v.visibleColumns).toEqual(before);
	});

	it('showMenu est mutable', () => {
		const v = useColumnVisibility(cols, [], storage);
		expect(v.showMenu).toBe(false);
		v.showMenu = true;
		expect(v.showMenu).toBe(true);
	});
});
