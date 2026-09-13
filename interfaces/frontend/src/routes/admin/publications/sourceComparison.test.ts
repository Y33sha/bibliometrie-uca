import { describe, expect, it } from 'vitest';
import {
	comparisonRows,
	isDivergent,
	orderRecords,
	type ComparisonRow,
	type SourceRecord,
} from './sourceComparison';

function record(overrides: Partial<SourceRecord>): SourceRecord {
	return {
		id: 1,
		source: 'hal',
		source_id: 'hal-1',
		doi: null,
		identifiers: {},
		title: 'Titre',
		title_normalized: 'titre',
		doc_type: 'article',
		pub_year: 2024,
		language: 'en',
		oa_status: 'green',
		journal_id: null,
		journal_title: null,
		journal_raw_title: null,
		journal_raw_issn: null,
		journal_raw_eissn: null,
		publisher_id: null,
		publisher_name: null,
		publisher_raw_name: null,
		container_title: null,
		volume: null,
		issue: null,
		pages: null,
		article_number: null,
		...overrides,
	};
}

function row(rows: ComparisonRow[], key: string): ComparisonRow {
	const found = rows.find((r) => r.key === key);
	if (!found) throw new Error(`ligne ${key} absente`);
	return found;
}

describe('orderRecords', () => {
	it("suit l'ordre d'affichage des sources, puis l'identifiant dans la source", () => {
		const ordered = orderRecords([
			record({ id: 1, source: 'wos', source_id: 'w1' }),
			record({ id: 2, source: 'openalex', source_id: 'W2' }),
			record({ id: 3, source: 'hal', source_id: 'hal-2' }),
			record({ id: 4, source: 'hal', source_id: 'hal-1' }),
		]);
		expect(ordered.map((r) => r.id)).toEqual([4, 3, 2, 1]);
	});
});

describe('isDivergent', () => {
	it('ignore la casse, les espaces et les valeurs absentes', () => {
		expect(isDivergent(['Un  titre', 'un titre ', null, ''])).toBe(false);
	});

	it('signale deux valeurs différentes', () => {
		expect(isDivergent([2023, 2024])).toBe(true);
	});
});

describe('comparisonRows', () => {
	it("ajoute une ligne par type d'identifiant présent", () => {
		const rows = comparisonRows([
			record({ identifiers: { pmid: ['123'] } }),
			record({ id: 2, identifiers: { hal_id: ['hal-1'], pmid: ['123'] } }),
		]);
		const identifierKeys = rows.map((r) => r.key).filter((k) => k.startsWith('identifier:'));
		expect(identifierKeys).toEqual(['identifier:hal_id', 'identifier:pmid']);
		expect(row(rows, 'identifier:pmid').divergent).toBe(false);
	});

	it("compare les titres normalisés : un trait d'union ne crée pas d'écart", () => {
		const rows = comparisonRows([
			record({ title: 'Self-assembly of gels', title_normalized: 'self assembly of gels' }),
			record({ id: 2, title: 'Selfassembly of gels', title_normalized: 'selfassembly of gels' }),
		]);
		expect(row(rows, 'title').divergent).toBe(false);
	});

	it('place les ISSN sous la revue et masque les lignes vides dans toutes les sources', () => {
		const keys = comparisonRows([
			record({ journal_raw_title: 'Revue', journal_raw_issn: '1234-5678' }),
		]).map((r) => r.key);
		const journal = keys.indexOf('journal');
		expect(keys.slice(journal, journal + 2)).toEqual(['journal', 'issn']);
		expect(keys).not.toContain('eissn');
		expect(keys).not.toContain('volume');
	});

	it('met en note le nom de revue donné par la source quand il diffère du référentiel', () => {
		const rows = comparisonRows([
			record({ journal_id: 7, journal_title: 'Nature', journal_raw_title: 'Nature (London)' }),
		]);
		expect(row(rows, 'journal').cells).toEqual([
			{ text: 'Nature', link: { kind: 'journals', id: 7 }, note: 'Nature (London)' },
		]);
	});

	it('signale une revue rattachée à deux entrées différentes du référentiel', () => {
		const rows = comparisonRows([
			record({ journal_id: 7, journal_title: 'Nature' }),
			record({ id: 2, journal_id: 8, journal_title: 'Nature' }),
		]);
		expect(row(rows, 'journal').divergent).toBe(true);
	});
});
