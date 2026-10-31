import { beforeAll, describe, expect, it, vi } from 'vitest';
import { loadSources } from '#lib/sources.svelte.js';
import {
	authorRows,
	comparisonRows,
	isDivergent,
	orderRecords,
	otherRoles,
	type ComparisonRow,
	type SourceRecord,
	type SourceContribution,
} from './sourceComparison';

function record(overrides: Partial<SourceRecord>): SourceRecord {
	return {
		id: 1,
		source: 'hal',
		source_id: 'hal-1',
		record_url: 'https://hal.science/hal-1',
		doi: null,
		identifiers: [],
		title: 'Titre',
		title_normalized: 'titre',
		doc_type: 'article',
		raw_doc_type: null,
		doc_type_uncorrected: null,
		doc_type_corrected_by: null,
		publication_year: 2024,
		language: 'en',
		language_name: 'Anglais',
		language_raw: null,
		serial_id: null,
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

// Ordre d'affichage des sources, tel que `/api/sources` le sert.
vi.mock('#lib/api/index.js', () => ({
	api: async () =>
		['hal', 'openalex', 'wos'].map((value) => ({ value, label_fr: value }))
}));

describe('orderRecords', () => {
	beforeAll(() => loadSources());

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
			record({ identifiers: [{ type: 'pmid', value: '123' }] }),
			record({
				id: 2,
				identifiers: [
					{ type: 'hal_id', value: 'hal-1' },
					{ type: 'pmid', value: '123' },
				],
			}),
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
		const serial = keys.indexOf('serial');
		expect(keys.slice(serial, serial + 2)).toEqual(['serial', 'issn']);
		expect(keys).not.toContain('eissn');
		expect(keys).not.toContain('volume');
	});

	it('met en note le nom de revue donné par la source quand il diffère du référentiel', () => {
		const rows = comparisonRows([
			record({ serial_id: 7, journal_title: 'Nature', journal_raw_title: 'Nature (London)' }),
		]);
		expect(row(rows, 'serial').cells).toEqual([
			{ text: 'Nature', link: { kind: 'serials', id: 7 }, note: 'Nature (London)' },
		]);
	});

	it('signale une revue rattachée à deux entrées différentes du référentiel', () => {
		const rows = comparisonRows([
			record({ serial_id: 7, journal_title: 'Nature' }),
			record({ id: 2, serial_id: 8, journal_title: 'Nature' }),
		]);
		expect(row(rows, 'serial').divergent).toBe(true);
	});

	it("affiche le type corrigé, le type d'avant correction et en note le type de la source", () => {
		const rows = comparisonRows([
			record({
				doc_type: 'media',
				raw_doc_type: 'journal-article',
				doc_type_uncorrected: 'article',
				doc_type_corrected_by: 'SERIAL_TYPE_MEDIA_TO_MEDIA',
			}),
		]);
		expect(row(rows, 'doc_type').cells).toEqual([
			{
				text: 'media',
				note: 'journal-article',
				corrected: { from: 'article', rule: 'SERIAL_TYPE_MEDIA_TO_MEDIA' },
			},
		]);
	});

	it('affiche le nom de la langue, avec en note la valeur que donnait la source', () => {
		const rows = comparisonRows([record({ source: 'wos', language_raw: 'English' })]);
		expect(row(rows, 'language').cells).toEqual([{ text: 'Anglais', note: 'English' }]);
	});
});

function contribution(overrides: Partial<SourceContribution>): SourceContribution {
	return {
		id: 1,
		source_record_id: 1,
		position: 0,
		full_name: 'Anne Martin',
		roles: ['author'],
		person_id: null,
		in_perimeter: false,
		structure_ids: null,
		raw_affiliation: null,
		countries: null,
		contribution_id: null,
		reference_position: null,
		method: null,
		score: null,
		margin: null,
		...overrides,
	};
}

describe('authorRows', () => {
	const records = [record({ id: 1, source: 'hal' }), record({ id: 2, source: 'openalex' })];

	it("réunit les contributions sources d'un groupe sur une ligne, dans l'ordre de la liste de référence", () => {
		const rows = authorRows(records, [
			contribution({ id: 11, source_record_id: 1, position: 1, contribution_id: 7, reference_position: 1 }),
			contribution({ id: 21, source_record_id: 2, position: 0, contribution_id: 7, reference_position: 1 }),
			contribution({ id: 10, source_record_id: 1, position: 0, contribution_id: 6, reference_position: 0 }),
		]);
		expect(rows.map((r) => r.cells.map((c) => c?.id ?? null))).toEqual([
			[10, null],
			[11, 21],
		]);
		expect(rows.map((r) => r.divergent)).toEqual([true, false]);
	});

	it('place une contribution source hors des groupes à sa position, et les contributions sources sans position en dernier', () => {
		const rows = authorRows(records, [
			contribution({ id: 30, source_record_id: 1, position: null, roles: ['jury_member'] }),
			contribution({ id: 12, source_record_id: 1, position: 2 }),
			contribution({ id: 10, source_record_id: 1, position: 0, contribution_id: 6, reference_position: 0 }),
		]);
		expect(rows.map((r) => r.cells[0]?.id)).toEqual([10, 12, 30]);
	});
});

describe('otherRoles', () => {
	it("renvoie les rôles autres qu'auteur dans l'ordre d'affichage", () => {
		expect(otherRoles(contribution({ roles: ['contributor', 'author', 'editor'] }))).toEqual([
			'editor',
			'contributor',
		]);
		expect(otherRoles(contribution({ roles: ['author'] }))).toEqual([]);
	});
});
