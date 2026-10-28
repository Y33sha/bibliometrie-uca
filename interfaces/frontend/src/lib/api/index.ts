/**
 * Client API centralisé.
 *
 * - Helpers HTTP : `api` (GET avec annulation), `apiDetail` (GET du détail d'une entité, qui suit la redirection d'un identifiant fusionné), `post`, `put`, `patch`, `del` exposés pour les appels ad-hoc.
 * - Endpoints par domaine : exports groupés (`auth`, `persons`, `publications`, `structures`, …) — cf. fichiers frères de ce dossier.
 *
 * Règle : aucun `fetch()` direct dans `src/routes/*` ni dans `src/lib/*`. Toute nouvelle API doit passer par un endpoint typé ici.
 */

export { api, apiDetail, cancel, latestRequest, post, put, patch, del, ApiError, errorMessage } from './client';

export * as auth from './auth';
export * as persons from './persons';
export * as publications from './publications';
export * as contributions from './contributions';
export * as serials from './serials';
export * as publishers from './publishers';
export * as structures from './structures';
export * as perimeters from './perimeters';
export * as config from './config';
export * as nameForms from './nameForms';
export * as addresses from './addresses';
export * as orphanContributions from './orphanContributions';
