import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiSpy = vi.fn();
vi.mock('#lib/api/index.js', () => ({ api: (...args: unknown[]) => apiSpy(...args) }));

const { cachedEntityFacet, loadEntityFacet } = await import('./entityFacets');

const params = () => new URLSearchParams('year=2024');
const entities = [{ id: 1, label: 'Dupont', count: 3 }];

describe('options des filtres d’entité', () => {
	beforeEach(() => {
		apiSpy.mockReset();
	});

	it('envoie une seule requête pour deux chargements identiques, puis sert la réponse en cache', async () => {
		apiSpy.mockResolvedValue({ entities });
		const [a, b] = await Promise.all([
			loadEntityFacet('/api/cache-a', params, 'person'),
			loadEntityFacet('/api/cache-a', params, 'person'),
		]);
		expect(apiSpy).toHaveBeenCalledOnce();
		expect(apiSpy).toHaveBeenCalledWith('/api/cache-a/entities?year=2024&kind=person');
		expect(a).toEqual(entities);
		expect(b).toEqual(entities);
		expect(cachedEntityFacet('/api/cache-a', params, 'person')).toEqual(entities);
	});

	it('distingue le terme cherché, à partir de deux caractères', async () => {
		apiSpy.mockResolvedValue({ entities });
		await loadEntityFacet('/api/cache-b', params, 'person', 'd');
		await loadEntityFacet('/api/cache-b', params, 'person', 'du');
		expect(apiSpy.mock.calls.map(([url]) => url)).toEqual([
			'/api/cache-b/entities?year=2024&kind=person',
			'/api/cache-b/entities?year=2024&kind=person&entity_search=du',
		]);
	});

	it('retire du cache une requête en échec', async () => {
		apiSpy.mockRejectedValueOnce(new Error('panne')).mockResolvedValueOnce({ entities });
		await expect(loadEntityFacet('/api/cache-c', params, 'partner')).rejects.toThrow('panne');
		expect(cachedEntityFacet('/api/cache-c', params, 'partner')).toBeUndefined();
		expect(await loadEntityFacet('/api/cache-c', params, 'partner')).toEqual(entities);
	});
});
