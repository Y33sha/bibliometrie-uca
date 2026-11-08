/**
 * Options d'un filtre d'entité (auteur, organisation partenaire, revue, éditeur, sujet) : les entités les plus représentées sous les filtres actifs, avec leur décompte.
 *
 * Les réponses sont mises en cache par requête, pour une durée bornée. Le panneau des filtres charge ainsi d'avance les options d'un filtre replié ; le filtre déplié lit le cache.
 */
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';
import type { EntityKind } from '#lib/entityLabels.js';

type EntityFacetResponse = components['schemas']['EntityFacetResponse'];
export type EntityFacetEntity = EntityFacetResponse['entities'][number];

/** Durée de validité d'une réponse en cache. Une édition en session admin change des décomptes ; le cache les montre au plus pendant cette durée. */
const TTL_MS = 5 * 60_000;
/** Nombre de réponses gardées. Au-delà, la plus ancienne sort du cache. */
const MAX_ENTRIES = 50;

interface Entry {
	at: number;
	promise: Promise<EntityFacetEntity[]>;
	/** Entités reçues, une fois la réponse arrivée. */
	entities?: EntityFacetEntity[];
}

const cache = new Map<string, Entry>();

/** Adresse de la requête des options : les filtres actifs, le type d'entité et le terme cherché, s'il compte au moins deux caractères. */
function facetUrl(endpoint: string, buildParams: () => URLSearchParams, kind: EntityKind, search: string): string {
	const params = buildParams();
	params.set('kind', kind);
	if (search.trim().length >= 2) params.set('entity_search', search.trim());
	return `${endpoint}/entities?${params}`;
}

function liveEntry(url: string): Entry | undefined {
	const entry = cache.get(url);
	if (entry && Date.now() - entry.at > TTL_MS) {
		cache.delete(url);
		return undefined;
	}
	return entry;
}

/** Options déjà reçues pour cette requête, sinon `undefined`. */
export function cachedEntityFacet(
	endpoint: string,
	buildParams: () => URLSearchParams,
	kind: EntityKind,
	search = '',
): EntityFacetEntity[] | undefined {
	return liveEntry(facetUrl(endpoint, buildParams, kind, search))?.entities;
}

/** Charge les options, ou reprend la requête en cours ou en cache. Une requête en échec sort du cache. */
export function loadEntityFacet(
	endpoint: string,
	buildParams: () => URLSearchParams,
	kind: EntityKind,
	search = '',
): Promise<EntityFacetEntity[]> {
	const url = facetUrl(endpoint, buildParams, kind, search);
	const existing = liveEntry(url);
	if (existing) return existing.promise;
	const entry: Entry = { at: Date.now(), promise: Promise.resolve([]) };
	entry.promise = api<EntityFacetResponse>(url).then(
		(data) => (entry.entities = data.entities),
		(e) => {
			cache.delete(url);
			throw e;
		},
	);
	cache.set(url, entry);
	if (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
	return entry.promise;
}
