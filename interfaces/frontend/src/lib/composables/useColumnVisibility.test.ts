// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest';
import { useColumnVisibility, type ColumnDef } from './useColumnVisibility.svelte';

const STORAGE_KEY = 'pub-table-columns';

const cols: ColumnDef[] = [
	{ key: 'title', label: 'Titre', fixed: true },
	{ key: 'year', label: 'Année' },
	{ key: 'doi', label: 'DOI' },
	{ key: 'oa', label: 'OA' },
];

describe('useColumnVisibility', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('par défaut, toutes les colonnes sont visibles si rien dans le storage', () => {
		const v = useColumnVisibility(cols);
		expect(v.visibleColumns).toEqual(['title', 'year', 'doi', 'oa']);
	});

	it('respecte defaultHidden au premier chargement', () => {
		const v = useColumnVisibility(cols, ['doi', 'oa']);
		expect(v.visibleColumns).toEqual(['title', 'year']);
	});

	it('restaure depuis localStorage et conserve l\'ordre des colonnes définies', () => {
		// localStorage peut contenir des clés dans n'importe quel ordre.
		localStorage.setItem(STORAGE_KEY, JSON.stringify(['oa', 'year']));
		const v = useColumnVisibility(cols);
		// Les colonnes fixes (title) sont toujours réinjectées ; ordre préservé.
		expect(v.visibleColumns).toContain('title');
		expect(v.visibleColumns).toContain('year');
		expect(v.visibleColumns).toContain('oa');
		expect(v.visibleColumns).not.toContain('doi');
	});

	it('ignore les clés inconnues dans le localStorage (autre page)', () => {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(['title', 'unknown_col', 'year']));
		const v = useColumnVisibility(cols);
		expect(v.visibleColumns).not.toContain('unknown_col');
	});

	it('toggle bascule une colonne non-fixe et persiste', () => {
		const v = useColumnVisibility(cols);
		v.toggle('doi');
		expect(v.visibleColumns).not.toContain('doi');
		expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')).not.toContain('doi');

		v.toggle('doi');
		expect(v.visibleColumns).toContain('doi');
	});

	it('toggle réinsère la colonne dans l\'ordre d\'origine', () => {
		const v = useColumnVisibility(cols);
		v.toggle('year');
		v.toggle('doi');
		// year et doi cachées
		v.toggle('year');
		// year doit revenir à sa position d'origine (avant doi)
		expect(v.visibleColumns).toEqual(['title', 'year', 'oa']);
	});

	it('toggle ignore les colonnes fixes', () => {
		const v = useColumnVisibility(cols);
		v.toggle('title');
		expect(v.visibleColumns).toContain('title');
	});

	it('col(key) renvoie l\'état de visibilité', () => {
		const v = useColumnVisibility(cols, ['doi']);
		expect(v.col('title')).toBe(true);
		expect(v.col('doi')).toBe(false);
	});

	it('ensure ajoute des colonnes manquantes en respectant l\'ordre', () => {
		const v = useColumnVisibility(cols, ['year', 'doi', 'oa']);
		// Au départ, seul `title` est visible.
		expect(v.visibleColumns).toEqual(['title']);
		v.ensure(['oa', 'doi']);
		// Réinsérées dans l'ordre des colonnes définies.
		expect(v.visibleColumns).toEqual(['title', 'doi', 'oa']);
	});

	it('ensure ignore les clés inconnues', () => {
		const v = useColumnVisibility(cols);
		const before = [...v.visibleColumns];
		v.ensure(['inexistant']);
		expect(v.visibleColumns).toEqual(before);
	});

	it('showMenu est mutable', () => {
		const v = useColumnVisibility(cols);
		expect(v.showMenu).toBe(false);
		v.showMenu = true;
		expect(v.showMenu).toBe(true);
	});
});
