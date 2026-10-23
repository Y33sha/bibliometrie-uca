import type { components } from './api/schema';

export type StructInfo = components['schemas']['StructureInfo'];

/** Ce qu'une contribution source dit de son affiliation : adresses brutes et structures identifiées. */
export interface Affiliation {
	raw_affiliation?: string | null;
	structure_ids?: number[] | null;
}

interface Labelled {
	acronym?: string | null;
	name?: string | null;
}

/** Libellé affiché d'une structure : son acronyme, à défaut son nom. */
export function structureLabel(s: Labelled): string {
	return s.acronym || s.name || '';
}

/** Libellé d'une structure via son id, `#id` si l'id est absent du dictionnaire. */
export function structLabelById(structures: Record<string, StructInfo>, id: number): string {
	const s = structures[String(id)];
	return s ? structureLabel(s) : `#${id}`;
}

/** Comparateur alphabétique de structures sur leur libellé affiché, insensible à la casse et aux accents. */
export function compareStructureLabels(a: Labelled, b: Labelled): number {
	return structureLabel(a).localeCompare(structureLabel(b), 'fr', { sensitivity: 'base' });
}

export function structIsLabo(structures: Record<string, StructInfo>, id: number): boolean {
	return structures[String(id)]?.type === 'labo';
}

/**
 * Tooltip résumé des affiliations brutes + structures identifiées, en texte simple.
 *
 * L'affiliation brute et les libellés de structures proviennent des sources externes : le résultat est du texte rendu tel quel par `Tooltip` (jamais interprété comme HTML), les lignes séparées par des sauts de ligne.
 */
export function structsTooltip(a: Affiliation, structures: Record<string, StructInfo>): string {
	const parts: string[] = [];
	if (a.raw_affiliation) {
		parts.push(a.raw_affiliation);
	}
	if (a.structure_ids?.length) {
		parts.push(
			`Structures identifiées\u00a0: ${a.structure_ids.map((sid) => structLabelById(structures, sid)).join(', ')}`,
		);
	}
	return parts.join('\n');
}
