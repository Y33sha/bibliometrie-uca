import { describe, it, expect } from 'vitest';
import { useFilterPanel, type PanelStorage } from './useFilterPanel.svelte';

/** Stockage en mémoire, tenant lieu de celui du navigateur. */
function memoryStorage(): PanelStorage {
	const content = new Map<string, string>();
	return {
		getItem: (key) => content.get(key) ?? null,
		setItem: (key, value) => {
			content.set(key, value);
		},
	};
}

describe('useFilterPanel', () => {
	it("s'ouvre par défaut sur grand écran, et retient sa fermeture", () => {
		const storage = memoryStorage();
		const panel = useFilterPanel(storage, true);
		expect(panel.open).toBe(true);
		panel.open = false;
		expect(useFilterPanel(storage, true).open).toBe(false);
	});

	it("reste fermé à l'ouverture sur écran étroit, sans retenir l'état de l'écran étroit", () => {
		const storage = memoryStorage();
		const narrow = useFilterPanel(storage, false);
		expect(narrow.open).toBe(false);
		narrow.open = true;
		narrow.open = false;
		expect(useFilterPanel(storage, true).open).toBe(true);
	});

	it("déplie les filtres actifs, puis suit le choix de l'utilisateur, le temps de la page", () => {
		const storage = memoryStorage();
		const panel = useFilterPanel(storage, true);
		expect(panel.isExpanded('years', false)).toBe(false);
		expect(panel.isExpanded('labs', true)).toBe(true);
		panel.setExpanded('years', true);
		panel.setExpanded('labs', false);
		expect(panel.isExpanded('years', false)).toBe(true);
		expect(panel.isExpanded('labs', true)).toBe(false);
		const nextPage = useFilterPanel(storage, true);
		expect(nextPage.isExpanded('years', false)).toBe(false);
	});
});
