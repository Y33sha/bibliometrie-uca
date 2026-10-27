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

// Paramètre de requête de l'entité de chaque contexte, dans l'API des publications et des statistiques.
const CONTEXT_PARAM: Record<Exclude<PublicationListContext['kind'], 'all'>, string> = {
	subject: 'subject_id',
	lab: 'lab_id',
	person: 'person_id',
	serial: 'serial_id',
	publisher: 'publisher_id',
	monograph: 'monograph_id',
};

/** Paramètres de requête qui restreignent aux publications du contexte. */
export function contextParams(context: PublicationListContext): URLSearchParams {
	const params = new URLSearchParams();
	if (context.kind !== 'all') params.set(CONTEXT_PARAM[context.kind], String(context.id));
	return params;
}

/** Identifiant de l'entité du contexte quand elle est de type `kind`, en paramètre de requête. */
export function contextEntityId(
	context: PublicationListContext,
	kind: Exclude<PublicationListContext['kind'], 'all'>,
): string | null {
	return context.kind === kind ? String(context.id) : null;
}
