/**
 * Ensemble que montre une liste de publications : toutes, ou celles d'une entité.
 *
 * Le contexte fixe le filtre de son entité. Il détermine aussi les filtres propres à l'entité : le statut HAL pour un laboratoire, la correspondance et le périmètre pour une personne.
 */
export type PublicationListContext =
	| { kind: 'all' }
	| { kind: 'subject'; id: number }
	| { kind: 'lab'; id: number }
	| { kind: 'person'; id: number }
	| { kind: 'serial'; id: number }
	| { kind: 'publisher'; id: number }
	| { kind: 'monograph'; id: number };

/** Identifiant de l'entité du contexte quand elle est de type `kind`, en paramètre de requête. */
export function contextEntityId(
	context: PublicationListContext,
	kind: Exclude<PublicationListContext['kind'], 'all'>,
): string | null {
	return context.kind === kind ? String(context.id) : null;
}
