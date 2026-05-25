import type { LayoutLoad } from './$types';
import { docTypes } from '$lib/api';
import { docTypeLabels, type DocTypeLabels } from '$lib/stores/docTypes';

export const ssr = false;

export const load: LayoutLoad = async () => {
	const res = await docTypes.list();
	const labels: DocTypeLabels = {};
	for (const item of res.items) {
		labels[item.value] = { singular: item.singular, plural: item.plural };
	}
	// Set synchrone : garantit que les composants enfants voient les labels
	// dès leur mount (sinon un $effect dans +layout.svelte pourrait courir
	// après le mount des enfants).
	docTypeLabels.set(labels);
	return {};
};
