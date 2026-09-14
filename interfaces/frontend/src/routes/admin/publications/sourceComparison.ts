import type { components } from '$lib/api/schema';
import { docTypeSingular, oaLabelsMap } from '$lib/labels';
import { SOURCE_ORDER } from '$lib/sources';

export type SourceRecord = components['schemas']['SourcePublicationMetadataOut'];

/** Cible du lien d'une case : un DOI, ou une entrée du référentiel. Le gabarit compose l'adresse et en écrit l'hôte. */
export type CellLink = { kind: 'doi'; doi: string } | { kind: 'journals' | 'publishers'; id: number };

/** Case du tableau : texte affiché (`null` pour une valeur absente), lien éventuel, et en note le nom donné par la source quand il diffère du référentiel. */
export interface ComparisonCell {
	text: string | null;
	link?: CellLink;
	note?: string;
}

/** Ligne du tableau : un champ, une case par enregistrement. `divergent` signale au moins deux valeurs différentes. */
export interface ComparisonRow {
	key: string;
	label: string;
	cells: ComparisonCell[];
	divergent: boolean;
}

type Comparable = string | number | null | undefined;

interface Field {
	key: string;
	label: string;
	cell: (r: SourceRecord) => ComparisonCell;
	/** Valeur comparée d'un enregistrement à l'autre. */
	compared: (r: SourceRecord) => Comparable;
}

const IDENTIFIER_LABELS: Record<string, string> = {
	hal_id: 'HAL',
	nnt: 'NNT',
	pmid: 'PMID',
	pmcid: 'PMCID',
	arxiv_id: 'arXiv',
	isbn: 'ISBN',
	related_dois: 'DOI apparentés',
};

function rank(source: string): number {
	const i = SOURCE_ORDER.indexOf(source);
	return i < 0 ? SOURCE_ORDER.length : i;
}

/** Enregistrements dans l'ordre d'affichage des sources, puis par identifiant dans la source. */
export function orderRecords(records: SourceRecord[]): SourceRecord[] {
	return [...records].sort(
		(a, b) => rank(a.source) - rank(b.source) || a.source_id.localeCompare(b.source_id),
	);
}

function normalized(value: string | number): string {
	return String(value).trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Vrai quand au moins deux valeurs diffèrent, à la casse et aux espaces près. Les valeurs absentes n'entrent pas dans la comparaison. */
export function isDivergent(values: Comparable[]): boolean {
	const present = values.filter((v): v is string | number => v != null && v !== '');
	return new Set(present.map(normalized)).size > 1;
}

/** Revue ou éditeur : l'entrée du référentiel, avec en note le nom donné par la source quand il diffère. Sans rattachement au référentiel, le nom donné par la source. */
function referentialCell(
	id: number | null,
	name: string | null,
	rawName: string | null,
	kind: 'journals' | 'publishers',
): ComparisonCell {
	if (id == null) return { text: rawName };
	const note = rawName && name && normalized(rawName) !== normalized(name) ? rawName : undefined;
	return { text: name ?? rawName, link: { kind, id }, note };
}

/** Types d'identifiants portés par au moins un enregistrement : ceux de `IDENTIFIER_LABELS` dans leur ordre, puis les autres par ordre alphabétique. */
function identifierTypes(records: SourceRecord[]): string[] {
	const present = new Set(records.flatMap((r) => Object.keys(r.identifiers)));
	const known = Object.keys(IDENTIFIER_LABELS).filter((t) => present.has(t));
	const others = [...present].filter((t) => !(t in IDENTIFIER_LABELS)).sort();
	return [...known, ...others];
}

function identifierField(type: string): Field {
	const values = (r: SourceRecord) => r.identifiers[type] ?? [];
	return {
		key: `identifier:${type}`,
		label: IDENTIFIER_LABELS[type] ?? type,
		cell: (r) => ({ text: values(r).join(', ') || null }),
		compared: (r) => [...values(r)].sort().join(' ') || null,
	};
}

/** Champ affiché et comparé tel quel. */
function textField(key: string, label: string, get: (r: SourceRecord) => string | null): Field {
	return { key, label, cell: (r) => ({ text: get(r) }), compared: get };
}

function fields(records: SourceRecord[]): Field[] {
	return [
		{
			key: 'doi',
			label: 'DOI',
			cell: (r) => ({ text: r.doi, link: r.doi ? { kind: 'doi', doi: r.doi } : undefined }),
			compared: (r) => r.doi,
		},
		...identifierTypes(records).map(identifierField),
		{
			key: 'title',
			label: 'Titre',
			cell: (r) => ({ text: r.title }),
			// Forme normalisée sans espaces : un trait d'union présent, absent ou remplacé par une espace ne crée pas d'écart.
			compared: (r) => (r.title_normalized ?? r.title).replace(/\s+/g, ''),
		},
		{
			key: 'doc_type',
			label: 'Type',
			cell: (r) => ({ text: r.doc_type ? (docTypeSingular[r.doc_type] ?? r.doc_type) : null }),
			compared: (r) => r.doc_type,
		},
		{
			key: 'pub_year',
			label: 'Année',
			cell: (r) => ({ text: r.pub_year?.toString() ?? null }),
			compared: (r) => r.pub_year,
		},
		{
			key: 'journal',
			label: 'Revue',
			cell: (r) => referentialCell(r.journal_id, r.journal_title, r.journal_raw_title, 'journals'),
			compared: (r) => (r.journal_id != null ? `#${r.journal_id}` : r.journal_raw_title),
		},
		textField('issn', 'ISSN', (r) => r.journal_raw_issn),
		textField('eissn', 'e-ISSN', (r) => r.journal_raw_eissn),
		{
			key: 'publisher',
			label: 'Éditeur',
			cell: (r) =>
				referentialCell(r.publisher_id, r.publisher_name, r.publisher_raw_name, 'publishers'),
			compared: (r) => (r.publisher_id != null ? `#${r.publisher_id}` : r.publisher_raw_name),
		},
		textField('container_title', 'Conteneur', (r) => r.container_title),
		textField('volume', 'Volume', (r) => r.volume),
		textField('issue', 'Numéro', (r) => r.issue),
		textField('pages', 'Pages', (r) => r.pages),
		textField('article_number', "Numéro d'article", (r) => r.article_number),
		{
			key: 'language',
			label: 'Langue',
			// Nom du référentiel, avec en note la valeur que donnait la source quand la normalisation l'a changée.
			cell: (r) => ({ text: r.language_name ?? r.language, note: r.language_raw ?? undefined }),
			compared: (r) => r.language,
		},
		{
			key: 'oa_status',
			label: 'Statut OA',
			cell: (r) => ({ text: r.oa_status ? (oaLabelsMap[r.oa_status] ?? r.oa_status) : null }),
			compared: (r) => r.oa_status,
		},
	];
}

/** Lignes du tableau de confrontation, une par champ renseigné dans au moins un enregistrement, pour des enregistrements déjà ordonnés. */
export function comparisonRows(records: SourceRecord[]): ComparisonRow[] {
	return fields(records)
		.map((f) => ({
			key: f.key,
			label: f.label,
			cells: records.map((r) => f.cell(r)),
			divergent: isDivergent(records.map((r) => f.compared(r))),
		}))
		.filter((row) => row.cells.some((c) => c.text !== null));
}
