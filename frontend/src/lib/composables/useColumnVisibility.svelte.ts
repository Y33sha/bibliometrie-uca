/**
 * Composable pour la visibilité des colonnes d'un tableau de publications.
 *
 * - Clé localStorage partagée entre toutes les pages (pub-table-columns)
 * - Colonnes fixes (non décochables) définies par `fixed: true`
 * - Colonnes masquées par défaut via `defaultHidden`
 * - Chaque page passe ses propres définitions de colonnes
 */

const STORAGE_KEY = 'pub-table-columns';

export interface ColumnDef {
	key: string;
	label: string;
	fixed?: boolean;
}

export function useColumnVisibility(columns: ColumnDef[], defaultHidden: string[] = []) {
	const allKeys = columns.map(c => c.key);
	const fixedKeys = columns.filter(c => c.fixed).map(c => c.key);
	const defaultVisible = allKeys.filter(k => !defaultHidden.includes(k));

	function load(): string[] {
		try {
			const stored = localStorage.getItem(STORAGE_KEY);
			if (stored) {
				const parsed = JSON.parse(stored) as string[];
				// Garder uniquement les clés connues de cette page + toujours inclure les fixes
				const valid = parsed.filter(k => allKeys.includes(k));
				return [...new Set([...fixedKeys, ...valid])];
			}
		} catch { /* ignore */ }
		return [...defaultVisible];
	}

	let visibleColumns = $state(load());
	let showMenu = $state(false);

	function toggle(key: string) {
		const col = columns.find(c => c.key === key);
		if (col?.fixed) return;
		if (visibleColumns.includes(key)) {
			visibleColumns = visibleColumns.filter(k => k !== key);
		} else {
			// Réinsérer dans l'ordre d'origine
			visibleColumns = allKeys.filter(k => k === key || visibleColumns.includes(k));
		}
		localStorage.setItem(STORAGE_KEY, JSON.stringify(visibleColumns));
	}

	function col(key: string): boolean {
		return visibleColumns.includes(key);
	}

	return {
		get columns() { return columns; },
		get visibleColumns() { return visibleColumns; },
		get showMenu() { return showMenu; },
		set showMenu(v: boolean) { showMenu = v; },
		toggle,
		col,
	};
}
