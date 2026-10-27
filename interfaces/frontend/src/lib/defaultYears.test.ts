import { describe, it, expect } from 'vitest';
import { defaultYears } from './defaultYears';

describe('defaultYears', () => {
	it('exclut les années postérieures à l\'année courante', () => {
		const years = ['2020', '2021', '2022', '2023', '2024', '2025', '2026', '2027'];
		expect(defaultYears(years, 2026)).toEqual(['2026', '2025', '2024', '2023', '2022']);
	});

	it('renvoie toutes les années quand il y en a moins de cinq', () => {
		expect(defaultYears(['2025', '2024'], 2026)).toEqual(['2025', '2024']);
	});
});
