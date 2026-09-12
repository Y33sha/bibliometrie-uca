/**
 * Libellés des éditeurs, des revues, des personnes et des sujets, par identifiant. Un libellé connu par ailleurs (option choisie dans une facette) est retenu ; les autres sont lus sur `/api/entity-labels`, qui rend `null` pour une entité introuvable.
 */
import { api } from '$lib/api';
import type { components } from '$lib/api/schema';
import { titleCase } from '$lib/utils';

type EntityLabelResponse = components['schemas']['EntityLabelResponse'];

export type EntityKind = 'publisher' | 'journal' | 'person' | 'subject';

/** Libellé affiché. Un nom de personne passe par `titleCase`, certains étant enregistrés en majuscules. */
export function displayEntityLabel(kind: EntityKind, label: string): string {
	return kind === 'person' ? titleCase(label) : label;
}

const labels = new Map<string, Promise<string | null>>();

export function rememberEntityLabel(kind: EntityKind, id: string, label: string): void {
	labels.set(`${kind}:${id}`, Promise.resolve(label));
}

export function entityLabel(kind: EntityKind, id: string): Promise<string | null> {
	const key = `${kind}:${id}`;
	const known = labels.get(key);
	if (known) return known;
	const label = api<EntityLabelResponse>(`/api/entity-labels?kind=${kind}&entity_id=${id}`).then((d) =>
		d.label === null ? null : displayEntityLabel(kind, d.label),
	);
	// Une lecture en échec est retentée au prochain appel.
	label.catch(() => labels.delete(key));
	labels.set(key, label);
	return label;
}
