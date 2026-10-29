import type { components } from '#lib/api/schema.js';
import { docTypeLabel } from '#lib/docTypes.svelte.js';
import { CONTRIBUTION_ROLE_ORDER, oaStatusLabel } from '#lib/labels.js';
import { sourceOrder } from '#lib/sources.svelte.js';

export type SourceRecord = components['schemas']['SourceRecordMetadataOut'];
export type SourceContribution = components['schemas']['SourceContributionOut'];

/** Cible du lien d'une case : un DOI, ou une entrée du référentiel. Le gabarit compose l'adresse et en écrit l'hôte. */
export type CellLink = { kind: 'doi'; doi: string } | { kind: 'serials' | 'publishers'; id: number };

/** Case du tableau : texte affiché (`null` pour une valeur absente), lien éventuel, et en note le nom donné par la source quand il diffère du référentiel. `title` signale un titre de publication, rendu par `PublicationTitle`. */
export interface ComparisonCell {
	text: string | null;
	link?: CellLink;
	note?: string;
	title?: boolean;
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
	doi: 'DOI apparentés',
};

function rank(source: string): number {
	const order = sourceOrder();
	const i = order.indexOf(source);
	return i < 0 ? order.length : i;
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
	kind: 'serials' | 'publishers',
): ComparisonCell {
	if (id == null) return { text: rawName };
	const note = rawName && name && normalized(rawName) !== normalized(name) ? rawName : undefined;
	return { text: name ?? rawName, link: { kind, id }, note };
}

/** Types d'identifiants portés par au moins un enregistrement : ceux de `IDENTIFIER_LABELS` dans leur ordre, puis les autres par ordre alphabétique. */
function identifierTypes(records: SourceRecord[]): string[] {
	const present = new Set(records.flatMap((r) => r.identifiers.map((i) => i.type)));
	const known = Object.keys(IDENTIFIER_LABELS).filter((t) => present.has(t));
	const others = [...present].filter((t) => !(t in IDENTIFIER_LABELS)).sort();
	return [...known, ...others];
}

function identifierField(type: string): Field {
	const values = (r: SourceRecord) =>
		r.identifiers.filter((i) => i.type === type).map((i) => i.value);
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
			cell: (r) => ({ text: r.title, title: true }),
			// Forme normalisée sans espaces : un trait d'union présent, absent ou remplacé par une espace ne crée pas d'écart.
			compared: (r) => (r.title_normalized ?? r.title).replace(/\s+/g, ''),
		},
		{
			key: 'doc_type',
			label: 'Type',
			cell: (r) => ({ text: r.doc_type ? docTypeLabel(r.doc_type) : null }),
			compared: (r) => r.doc_type,
		},
		{
			key: 'publication_year',
			label: 'Année',
			cell: (r) => ({ text: r.publication_year?.toString() ?? null }),
			compared: (r) => r.publication_year,
		},
		{
			key: 'serial',
			label: 'Publication en série',
			cell: (r) => referentialCell(r.serial_id, r.journal_title, r.journal_raw_title, 'serials'),
			compared: (r) => (r.serial_id != null ? `#${r.serial_id}` : r.journal_raw_title),
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
			cell: (r) => ({ text: r.oa_status ? oaStatusLabel(r.oa_status) : null }),
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

/** Ligne des listes d'auteurs : les contributions sources d'un groupe, ou une contribution source hors des groupes, une case par enregistrement (`null` quand l'enregistrement n'en donne pas). */
export interface AuthorRow {
	key: string;
	cells: (SourceContribution | null)[];
	/** Un enregistrement qui donne des contributions sources n'en a aucune dans la ligne. */
	divergent: boolean;
}

/** Rôles d'une contribution source autres qu'auteur, dans l'ordre d'affichage. */
export function otherRoles(s: SourceContribution): string[] {
	const rank = (role: string) => {
		const i = CONTRIBUTION_ROLE_ORDER.indexOf(role);
		return i < 0 ? CONTRIBUTION_ROLE_ORDER.length : i;
	};
	return (s.roles ?? []).filter((r) => r !== 'author').sort((a, b) => rank(a) - rank(b));
}

/** Lignes des listes d'auteurs, pour des enregistrements déjà ordonnés : une ligne par contribution, une par contribution source hors des contributions, dans l'ordre de la liste de référence. Les lignes sans position viennent en dernier, par nom. */
export function authorRows(records: SourceRecord[], contributions: SourceContribution[]): AuthorRow[] {
	const column = new Map(records.map((r, i) => [r.id, i]));
	const members = new Map<string, SourceContribution[]>();
	const present = new Set<number>();
	for (const s of contributions) {
		const col = column.get(s.source_record_id);
		if (col === undefined) continue;
		const key = s.contribution_id != null ? `g${s.contribution_id}` : `s${s.id}`;
		members.set(key, [...(members.get(key) ?? []), s]);
		present.add(col);
	}
	const rows = [...members].map(([key, group]) => {
		const cells: (SourceContribution | null)[] = records.map(() => null);
		for (const s of group) cells[column.get(s.source_record_id)!] = s;
		const positions = group.map((s) => s.position).filter((p): p is number => p != null);
		return {
			row: { key, cells, divergent: group.length < present.size },
			position: group[0].reference_position ?? (positions.length ? Math.min(...positions) : Infinity),
			name: group[0].full_name ?? '',
		};
	});
	rows.sort(
		(a, b) =>
			a.position - b.position ||
			a.name.localeCompare(b.name) ||
			a.row.key.localeCompare(b.row.key),
	);
	return rows.map((r) => r.row);
}
