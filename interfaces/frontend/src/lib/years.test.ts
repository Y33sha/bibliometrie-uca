import { describe, it, expect } from 'vitest';
import { defaultYears, pivotAxisYears } from './years';

describe('defaultYears', () => {
	it("retient l'année courante et les cinq précédentes, sans les années postérieures", () => {
		const years = ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026', '2027'];
		expect(defaultYears(years, 2026)).toEqual(['2026', '2025', '2024', '2023', '2022', '2021']);
	});

	it('va de la première à la dernière année présente de la fenêtre', () => {
		expect(defaultYears(['2018', '2024', '2025'], 2026)).toEqual(['2025', '2024']);
	});

	it('garde les années vides entre deux années présentes', () => {
		expect(defaultYears(['2021', '2024'], 2026)).toEqual(['2024', '2023', '2022', '2021']);
	});

	it('ignore les publications sans année', () => {
		expect(defaultYears(['null', '2025'], 2026)).toEqual(['2025']);
	});
});

describe('pivotAxisYears', () => {
	const row = (year: number | null, value: number) => ({ year, value });

	it('garde les années vides de la plage', () => {
		expect(pivotAxisYears([row(2020, 40), row(2023, 60)], null)).toEqual(['2020', '2021', '2022', '2023']);
	});

	it('écarte aux deux bouts les années qui réunissent moins de 1 % du total', () => {
		expect(pivotAxisYears([row(1990, 0.5), row(2020, 50), row(2021, 49.5)], null)).toEqual(['2020', '2021']);
	});

	it('ignore les publications sans année', () => {
		expect(pivotAxisYears([row(null, 90), row(2022, 10)], null)).toEqual(['2022']);
	});

	it("reprend les années du filtre d'années, vides comprises", () => {
		expect(pivotAxisYears([row(2022, 10)], '2023,2021,2022')).toEqual(['2021', '2022', '2023']);
	});
});
