// Types de document : libellés et familles servis par l'API, couleurs locales.
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type DocTypeFamilyOut = components['schemas']['DocTypeFamilyOut'];

/** Famille de types de document, ses types dans l'ordre d'affichage. */
export type DocTypeFamily = { key: string; label: string; types: string[] };

const docTypes = $state({
	loaded: false,
	families: [] as DocTypeFamily[],
	singular: {} as Record<string, string>,
	plural: {} as Record<string, string>,
	familyOf: {} as Record<string, string>,
});

let loading: Promise<void> | null = null;

/** Charge les types de document une seule fois. Un échec laisse les clés brutes à l'affichage, et l'appel suivant réessaie. */
export function loadDocTypes(): Promise<void> {
	loading ??= api<DocTypeFamilyOut[]>('/api/publications/doc-types')
		.then((families) => {
			const types = families.flatMap((f) => f.types.map((t) => ({ ...t, family: f.key })));
			docTypes.families = families.map((f) => ({ key: f.key, label: f.label, types: f.types.map((t) => t.value) }));
			docTypes.singular = Object.fromEntries(types.map((t) => [t.value, t.label]));
			docTypes.plural = Object.fromEntries(types.map((t) => [t.value, t.plural_label]));
			docTypes.familyOf = Object.fromEntries(types.map((t) => [t.value, t.family]));
		})
		.catch(() => {
			loading = null;
		})
		.finally(() => {
			docTypes.loaded = true;
		});
	return loading;
}

/** Le premier chargement est terminé, réussi ou non. */
export function docTypesLoaded(): boolean {
	return docTypes.loaded;
}

/** Libellé (singulier) d'un `doc_type`, sinon la valeur brute. */
export function docTypeLabel(docType: string): string {
	return docTypes.singular[docType] ?? docType;
}

/** Libellés (pluriel) des `doc_type`. */
export function docTypePluralLabels(): Record<string, string> {
	return docTypes.plural;
}

/** Familles dans l'ordre d'affichage. */
export function docTypeFamilies(): DocTypeFamily[] {
	return docTypes.families;
}

/** Types de la famille « publications » : défaut du filtre de types sur les listes générales (statistiques et publications), appliqué quand l'URL ne porte pas de filtre de types explicite. */
export function publicationsDocTypes(): string[] {
	return docTypes.families.find((f) => f.key === 'publications')?.types ?? [];
}

/** Clés de groupement des types de document qui ont leur couleur, dans la variable CSS `--doctype-<clé>` de `shared.css`. */
const DOC_TYPE_COLOR_KEYS = new Set([
	'article',
	'review',
	'preprints',
	'conference_paper',
	'book',
	'book_chapter',
	'data_paper',
	'conferences',
	'theses',
	'data',
	'misc',
]);

/** Variable CSS de la couleur d'une clé de groupement des types de document (`doc_type_grouped`), sans le préfixe `--`. Une clé sans couleur prend celle de `misc`. */
export function docTypeGroupColorVar(key: string): string {
	return `doctype-${DOC_TYPE_COLOR_KEYS.has(key) ? key : 'misc'}`;
}

/** Variable CSS de la couleur d'un `doc_type`, sans le préfixe `--` : celle de sa clé de groupement dans la page Statistiques. Les types de la famille « publications » gardent leur couleur propre, les autres prennent celle de leur famille. */
export function docTypeColorVar(docType: string): string {
	const family = docTypes.familyOf[docType] ?? 'misc';
	return docTypeGroupColorVar(family === 'publications' ? docType : family);
}
