import { describe, it, expect } from 'vitest';
import { defaultYears } from './defaultYears';

describe('defaultYears', () => {
	it("retient l'année courante et les cinq précédentes, sans les années postérieures", () => {
		const years = ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026', '2027'];
		expect(defaultYears(years, 2026)).toEqual(['2026', '2025', '2024', '2023', '2022', '2021']);
	});

	it('retient seulement les années présentes de la fenêtre', () => {
		expect(defaultYears(['2018', '2024', '2025'], 2026)).toEqual(['2025', '2024']);
	});
});
