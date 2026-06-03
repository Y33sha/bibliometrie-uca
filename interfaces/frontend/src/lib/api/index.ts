/**
 * Client API centralisé.
 *
 * - Helpers HTTP : `api` (GET avec annulation), `post`, `put`, `patch`, `del`
 *   exposés pour les appels ad-hoc.
 * - Endpoints par domaine : exports groupés (`auth`, `persons`, `publications`,
 *   `structures`, …) — cf. fichiers frères de ce dossier.
 *
 * Règle : aucun `fetch()` direct dans `src/routes/*` ni dans `src/lib/*`.
 * Toute nouvelle API doit passer par un endpoint typé ici.
 */

export { api, post, put, patch, del, ApiError } from './client';

export * as auth from './auth';
export * as persons from './persons';
export * as authorships from './authorships';
export * as journals from './journals';
export * as publishers from './publishers';
export * as structures from './structures';
export * as perimeters from './perimeters';
export * as config from './config';
export * as nameForms from './nameForms';
export * as addresses from './addresses';
export * as orphanAuthorships from './orphanAuthorships';
export * as duplicates from './duplicates';
