import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mocks SvelteKit : l'URL courante est modifiable, l'écriture d'un paramètre est capturée.
const page = { url: new URL('http://localhost/publications') };
vi.mock('$app/state', () => ({ page }));
const setQueryParamSpy = vi.fn();
vi.mock('#lib/url.js', () => ({ setQueryParam: (...args: unknown[]) => setQueryParamSpy(...args) }));

// Import APRÈS les mocks pour qu'ils s'appliquent.
const { useTabParam } = await import('./useTabParam.svelte');

describe('useTabParam', () => {
	beforeEach(() => {
		setQueryParamSpy.mockClear();
	});

	it("lit l'onglet dans l'URL", () => {
		page.url = new URL('http://localhost/publications?tab=suspect-merges');
		expect(useTabParam(['suspect-merges'], () => true).current).toBe('suspect-merges');
	});

	it('rend la liste pour une clé inconnue ou hors session admin', () => {
		page.url = new URL('http://localhost/publications?tab=inconnu');
		expect(useTabParam(['suspect-merges'], () => true).current).toBe('all');
		page.url = new URL('http://localhost/publications?tab=suspect-merges');
		expect(useTabParam(['suspect-merges'], () => false).current).toBe('all');
	});

	it("écrit l'onglet dans l'URL, sans paramètre pour la liste", () => {
		const tab = useTabParam(['suspect-merges'], () => true);
		tab.select('suspect-merges');
		tab.select('all');
		expect(setQueryParamSpy.mock.calls).toEqual([
			['tab', 'suspect-merges'],
			['tab', null],
		]);
	});
});
