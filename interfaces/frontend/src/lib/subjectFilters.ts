/**
 * Registre des filtres de la liste des sujets.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { subjectVocabularyLabels } from '#lib/labels.js';

/** Rubriques du panneau des filtres des sujets, dans l'ordre d'affichage. */
export const SUBJECT_FILTER_GROUPS: readonly FilterGroup[] = [{ key: 'subject', label: 'Sujet' }];

export const SUBJECT_FILTERS: ListFilter[] = [
	{
		key: 'vocabularies',
		control: 'checkbox',
		label: 'Vocabulaires',
		param: 'vocabulary',
		group: 'subject',
		facet: { type: 'label_map', apiKey: 'vocabularies', labels: subjectVocabularyLabels },
	},
];
