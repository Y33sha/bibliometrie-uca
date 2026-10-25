import { describe, it, expect } from 'vitest';
import { crossrefMemberIds, crossrefMemberUrl } from './sources.svelte';

describe('membres Crossref', () => {
	it('construit le lien vers le rapport de participation', () => {
		expect(crossrefMemberUrl(297)).toBe('https://www.crossref.org/members/prep/297');
	});

	it('dédoublonne les membres des préfixes et ignore ceux qui en sont dépourvus', () => {
		const prefixes = [
			{ crossref_member_id: 297 },
			{ crossref_member_id: 297 },
			{ crossref_member_id: null },
			{ crossref_member_id: 93 }
		];
		expect(crossrefMemberIds(prefixes)).toEqual([297, 93]);
	});

	it('rend une liste vide quand aucun préfixe ne porte de membre', () => {
		expect(crossrefMemberIds([{ crossref_member_id: null }])).toEqual([]);
	});
});
