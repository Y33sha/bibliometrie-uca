// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import IdentifierEditor from './IdentifierEditor.svelte';
import type { Person } from './types';

describe('IdentifierEditor', () => {
	it('replie les identifiants rejetés', () => {
		const target = document.createElement('div');
		document.body.appendChild(target);
		const person = {
			id: 1,
			identifiers: [
				{ id: 1, id_type: 'orcid', id_value: '0000-0001-0000-0001', source: 'hal', status: 'confirmed' },
				{ id: 2, id_type: 'idref', id_value: '123456789', source: 'theses', status: 'rejected' },
			],
		} as unknown as Person;
		const component = mount(IdentifierEditor, {
			target,
			props: { person, form: null, onadd: () => {}, ontoggleForm: () => {}, onsetStatus: () => {} },
		});
		flushSync();

		const fold = target.querySelector('details')!;
		expect(fold.open).toBe(false);
		expect(fold.textContent).toContain('123456789');
		expect(fold.textContent).not.toContain('0000-0001-0000-0001');
		unmount(component);
		target.remove();
	});
});
