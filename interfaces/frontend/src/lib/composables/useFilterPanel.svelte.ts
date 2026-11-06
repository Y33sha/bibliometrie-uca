/**
 * État du panneau des filtres : ouvert ou fermé, et filtres dépliés.
 *
 * Le navigateur retient l'ouverture du panneau, pour toutes les listes. Le dépliage des filtres dure le temps de la page : un filtre est déplié quand il est actif, ou quand l'utilisateur l'a déplié.
 *
 * Le stockage est reçu en paramètre : l'application passe celui du navigateur, un test en passe un autre. `null` désactive la persistance.
 */

/** Ce que le composable attend d'un stockage : les deux opérations de `Storage` qu'il exerce. */
export interface PanelStorage {
	getItem(key: string): string | null;
	setItem(key: string, value: string): void;
}

const OPEN_KEY = 'filter-panel-open';

/** Largeur d'écran à partir de laquelle le panneau s'ouvre par défaut. En dessous, il recouvre la page. Les feuilles de style de `FilterLayout` et `FilterPanel` reprennent ce seuil. */
export const WIDE_SCREEN_QUERY = '(min-width: 1100px)';

function browserStorage(): PanelStorage | null {
	return typeof localStorage === 'undefined' ? null : localStorage;
}

function wideScreen(): boolean {
	return typeof matchMedia !== 'undefined' && matchMedia(WIDE_SCREEN_QUERY).matches;
}

export function useFilterPanel(storage: PanelStorage | null = browserStorage(), wide: boolean = wideScreen()) {
	// Sur écran étroit, le panneau recouvre la page : il s'ouvre seulement à la demande.
	const stored = storage?.getItem(OPEN_KEY);
	let open = $state(wide && stored !== '0');
	// Choix de l'utilisateur, par filtre.
	let expanded = $state<Record<string, boolean>>({});

	return {
		get open() {
			return open;
		},
		set open(value: boolean) {
			open = value;
			if (wide) storage?.setItem(OPEN_KEY, value ? '1' : '0');
		},
		/** Filtre déplié : choix de l'utilisateur, sinon `active`. */
		isExpanded(key: string, active: boolean): boolean {
			return expanded[key] ?? active;
		},
		setExpanded(key: string, value: boolean) {
			expanded = { ...expanded, [key]: value };
		},
	};
}
