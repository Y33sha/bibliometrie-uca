import { describe, expect, it } from 'vitest';
import { tabHref } from './tabs';

describe('tabHref', () => {
	it('compose une requête seule, onglet en tête, virgules lisibles', () => {
		expect(tabHref({ tab: 'theses', params: { doc_type: 'thesis,ongoing_thesis' } })).toBe('?tab=theses&doc_type=thesis,ongoing_thesis');
	});

	it('se contente de l’onglet sans paramètre', () => {
		expect(tabHref({ tab: 'persons' })).toBe('?tab=persons');
	});
});
