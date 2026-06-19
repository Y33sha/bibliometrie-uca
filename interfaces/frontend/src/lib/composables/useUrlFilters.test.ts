import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mocks SvelteKit : `goto` capture l'URL passée, base est un préfixe figé.
const gotoSpy = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => gotoSpy(...args),
}));
vi.mock('$app/paths', () => ({ base: '/bibliometrie' }));

// `syncUrl` appelle `goto(url, { replaceState, noScroll, keepFocus })`.
const GOTO_OPTS = { replaceState: true, noScroll: true, keepFocus: true };

// Import APRÈS les mocks pour qu'ils s'appliquent.
const { useUrlFilters } = await import('./useUrlFilters.svelte');

describe('useUrlFilters', () => {
	beforeEach(() => {
		gotoSpy.mockClear();
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	describe('syncUrl', () => {
		it('produit une URL sans queryparams si tous les filtres sont vides', () => {
			const f = useUrlFilters({
				basePath: '/publications',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
			});
			f.syncUrl(() => ({ years: [] }));
			expect(gotoSpy).toHaveBeenCalledWith('/bibliometrie/publications', GOTO_OPTS);
		});

		it('sérialise un string_array en CSV', () => {
			const f = useUrlFilters({
				basePath: '/publications',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
			});
			f.syncUrl(() => ({ years: ['2024', '2023'] }));
			expect(gotoSpy).toHaveBeenCalledWith(
				'/bibliometrie/publications?year=2024%2C2023',
				GOTO_OPTS,
			);
		});

		it('omet un single value à sa valeur par défaut', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { sort: { type: 'single', urlKey: 'sort', defaultValue: 'year_desc' } },
			});
			f.syncUrl(() => ({ sort: 'year_desc' }));
			expect(gotoSpy).toHaveBeenCalledWith('/bibliometrie/p', GOTO_OPTS);
		});

		it('inclut un single value différent de sa valeur par défaut', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { sort: { type: 'single', urlKey: 'sort', defaultValue: 'year_desc' } },
			});
			f.syncUrl(() => ({ sort: 'title' }));
			expect(gotoSpy).toHaveBeenCalledWith('/bibliometrie/p?sort=title', GOTO_OPTS);
		});

		it('sérialise les source_states en yes/no joints par virgule', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { sourceStates: { type: 'source_states', urlKey: 'sf' } },
			});
			f.syncUrl(() => ({ sourceStates: { hal: 'yes', oa: 'no', wos: 'any' } }));
			// `any` est ignoré (ni yes ni no)
			expect(gotoSpy).toHaveBeenCalled();
			const call = gotoSpy.mock.calls[0][0] as string;
			expect(call).toContain('sf=hal_yes%2Coa_no');
			expect(call).not.toContain('any');
		});

		it('omet la page si elle vaut 1', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { currentPage: { type: 'page', urlKey: 'page' } },
			});
			f.syncUrl(() => ({ currentPage: 1 }));
			expect(gotoSpy).toHaveBeenCalledWith('/bibliometrie/p', GOTO_OPTS);
		});

		it('inclut la page si elle est > 1', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { currentPage: { type: 'page', urlKey: 'page' } },
			});
			f.syncUrl(() => ({ currentPage: 3 }));
			expect(gotoSpy).toHaveBeenCalledWith('/bibliometrie/p?page=3', GOTO_OPTS);
		});

		it('préserve les keys URL non gérées par cette instance', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
				getCurrentParams: () => new URLSearchParams('tab=publications&foo=bar'),
			});
			f.syncUrl(() => ({ years: ['2024'] }));
			const call = gotoSpy.mock.calls[0][0] as string;
			expect(call).toContain('tab=publications');
			expect(call).toContain('foo=bar');
			expect(call).toContain('year=2024');
		});

		it('écrase une key gérée déjà présente dans l\'URL courante', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
				getCurrentParams: () => new URLSearchParams('year=2020&keep=me'),
			});
			f.syncUrl(() => ({ years: ['2024'] }));
			const call = gotoSpy.mock.calls[0][0] as string;
			expect(call).toContain('year=2024');
			expect(call).not.toContain('year=2020');
			expect(call).toContain('keep=me');
		});

		it('retire une key gérée si son state est vide, même si elle est dans l\'URL courante', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
				getCurrentParams: () => new URLSearchParams('year=2020&keep=me'),
			});
			f.syncUrl(() => ({ years: [] }));
			const call = gotoSpy.mock.calls[0][0] as string;
			expect(call).not.toContain('year');
			expect(call).toContain('keep=me');
		});
	});

	describe('restoreFromUrl', () => {
		it('restaure un string_array depuis CSV', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { years: { type: 'string_array', urlKey: 'year' } },
			});
			expect(f.restoreFromUrl(new URLSearchParams('year=2024,2023'))).toEqual({
				years: ['2024', '2023'],
			});
		});

		it('restaure un single value', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { sort: { type: 'single', urlKey: 'sort' } },
			});
			expect(f.restoreFromUrl(new URLSearchParams('sort=title'))).toEqual({ sort: 'title' });
		});

		it('restaure les source_states', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { sourceStates: { type: 'source_states', urlKey: 'sf' } },
			});
			expect(f.restoreFromUrl(new URLSearchParams('sf=hal_yes,oa_no'))).toEqual({
				sourceStates: { hal: 'yes', oa: 'no' },
			});
		});

		it('restaure une page numérique (défaut 1 si invalide)', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: { currentPage: { type: 'page', urlKey: 'page' } },
			});
			expect(f.restoreFromUrl(new URLSearchParams('page=5'))).toEqual({ currentPage: 5 });
			expect(f.restoreFromUrl(new URLSearchParams('page=zzz'))).toEqual({ currentPage: 1 });
		});

		it('omet les clés absentes de l\'URL', () => {
			const f = useUrlFilters({
				basePath: '/p',
				filters: {
					years: { type: 'string_array', urlKey: 'year' },
					sort: { type: 'single', urlKey: 'sort' },
				},
			});
			expect(f.restoreFromUrl(new URLSearchParams('year=2024'))).toEqual({
				years: ['2024'],
			});
		});
	});

	describe('debouncedSearch', () => {
		it('attend `debounceMs` avant de déclencher le callback', () => {
			const cb = vi.fn();
			const f = useUrlFilters({ basePath: '/p', filters: {}, debounceMs: 200 });
			const trigger = f.debouncedSearch(cb);

			trigger();
			vi.advanceTimersByTime(199);
			expect(cb).not.toHaveBeenCalled();
			vi.advanceTimersByTime(1);
			expect(cb).toHaveBeenCalledOnce();
		});

		it('annule le timer précédent à chaque appel (vrai debounce)', () => {
			const cb = vi.fn();
			const f = useUrlFilters({ basePath: '/p', filters: {}, debounceMs: 200 });
			const trigger = f.debouncedSearch(cb);

			trigger();
			vi.advanceTimersByTime(150);
			trigger();
			vi.advanceTimersByTime(150);
			expect(cb).not.toHaveBeenCalled(); // le 1er a été annulé
			vi.advanceTimersByTime(50);
			expect(cb).toHaveBeenCalledOnce();
		});
	});
});
