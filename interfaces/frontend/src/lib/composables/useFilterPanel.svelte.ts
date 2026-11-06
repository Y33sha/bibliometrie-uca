/**
 * État du panneau des filtres : ouvert ou fermé, et filtres dépliés. Un filtre est replié tant que l'utilisateur ne l'a pas déplié. Le navigateur retient cet état, pour toutes les listes.
 *
 * Le stockage est reçu en paramètre : l'application passe celui du navigateur, un test en passe un autre. `null` désactive la persistance.
 */

/** Ce que le composable attend d'un stockage : les deux opérations de `Storage` qu'il exerce. */
export interface PanelStorage {
	getItem(key: string): string | null;
	setItem(key: string, value: string): void;
}

const OPEN_KEY = 'filter-panel-open';
const EXPANDED_KEY = 'filter-panel-expanded';

/** Largeur d'écran à partir de laquelle le panneau s'ouvre par défaut. En dessous, il recouvre la page. Les feuilles de style de `FilterLayout` et `FilterPanel` reprennent ce seuil. */
export const WIDE_SCREEN_QUERY = '(min-width: 1100px)';

function browserStorage(): PanelStorage | null {
	return typeof localStorage === 'undefined' ? null : localStorage;
}

function wideScreen(): boolean {
	return typeof matchMedia !== 'undefined' && matchMedia(WIDE_SCREEN_QUERY).matches;
}

function readExpanded(storage: PanelStorage | null): Record<string, boolean> {
	try {
		const raw = storage?.getItem(EXPANDED_KEY);
		if (raw) return JSON.parse(raw) as Record<string, boolean>;
	} catch {
		/* valeur illisible : état par défaut */
	}
	return {};
}

export function useFilterPanel(storage: PanelStorage | null = browserStorage(), wide: boolean = wideScreen()) {
	// Sur écran étroit, le panneau recouvre la page : il s'ouvre seulement à la demande.
	const stored = storage?.getItem(OPEN_KEY);
	let open = $state(wide && stored !== '0');
	let expanded = $state(readExpanded(storage));

	return {
		get open() {
			return open;
		},
		set open(value: boolean) {
			open = value;
			if (wide) storage?.setItem(OPEN_KEY, value ? '1' : '0');
		},
		isExpanded(key: string): boolean {
			return expanded[key] ?? false;
		},
		setExpanded(key: string, value: boolean) {
			expanded = { ...expanded, [key]: value };
			storage?.setItem(EXPANDED_KEY, JSON.stringify(expanded));
		},
	};
}
