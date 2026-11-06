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

	it("déplie un filtre selon sa déclaration, puis selon le choix de l'utilisateur, retenu", () => {
		const storage = memoryStorage();
		const panel = useFilterPanel(storage, true);
		expect(panel.isExpanded('years', true)).toBe(true);
		expect(panel.isExpanded('languages', false)).toBe(false);
		panel.setExpanded('years', false);
		panel.setExpanded('languages', true);
		const reloaded = useFilterPanel(storage, true);
		expect(reloaded.isExpanded('years', true)).toBe(false);
		expect(reloaded.isExpanded('languages', false)).toBe(true);
	});
});
