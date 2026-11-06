import { entityLabel, rememberEntityLabel, type EntityKind } from '#lib/entityLabels.js';

/**
 * Libellés des entités sélectionnées d'un filtre, par id.
 *
 * Un id restauré depuis l'URL arrive sans son nom : `/api/entity-labels` le résout, et `entityLabel` mémorise la réponse. Un libellé choisi dans une liste d'options est enregistré par `remember`, sans relecture.
 */
export function useEntityLabels(kind: () => EntityKind, selected: () => string[]) {
	const labels = $state<Record<string, string>>({});

	$effect(() => {
		const k = kind();
		for (const id of selected()) {
			if (id in labels) continue;
			entityLabel(k, id)
				.then((l) => {
					labels[id] = l ?? id;
				})
				.catch(() => {});
		}
	});

	return {
		get labels() {
			return labels;
		},
		remember(id: string, label: string) {
			rememberEntityLabel(kind(), id, label);
			labels[id] = label;
		},
	};
}
