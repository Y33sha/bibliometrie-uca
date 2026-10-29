/**
 * Libellés, couleurs et ordre d'affichage des valeurs d'une dimension du pivot (`/api/stats/pivot`), partagés par la page Statistiques et les dashboards.
 *
 * Les valeurs open access reprennent les variables CSS des statuts ; les autres dimensions prennent la palette catégorielle.
 */
import { cssColor, oaStatusColor } from '#lib/components/charts/cssVar.js';
import { chartColor } from '#lib/components/charts/palette.js';
import { docTypeFamilies, docTypeGroupColorVar, docTypePluralLabels } from '#lib/docTypes.svelte.js';
import { licenseOrder, oaStatusLabel } from '#lib/labels.js';

const OA_VOIE_ORDER = ['diamond', 'gold', 'hybrid', 'bronze', 'green', 'embargoed', 'closed', 'unknown'];
const OA_ACCESS_ORDER = ['ouvert', 'embargo', 'ferme', 'indetermine'];
const OA_ACCESS_LABELS: Record<string, string> = {
	ouvert: 'Ouvert',
	embargo: 'Sous embargo',
	ferme: 'Fermé',
	indetermine: 'Indéterminé',
};
// Statut OA dont un niveau d'accès reprend la couleur.
const OA_ACCESS_STATUS: Record<string, string> = {
	ouvert: 'open',
	embargo: 'embargoed',
	ferme: 'closed',
	indetermine: 'unknown',
};

/** Libellé d'une valeur. `licenseLabel` donne le libellé d'une licence, servi par l'API. */
export function pivotValueLabel(
	dim: string,
	value: string,
	licenseLabel?: (value: string) => string | undefined,
): string {
	if (dim === 'oa_access') return OA_ACCESS_LABELS[value] ?? value;
	if (dim === 'oa_voie') return oaStatusLabel(value);
	if (dim === 'doc_type_grouped')
		return docTypePluralLabels()[value] ?? docTypeFamilies().find((f) => f.key === value)?.label ?? value;
	if (dim === 'license') return licenseLabel?.(value) ?? value;
	return value;
}

/** Couleur d'une valeur, `idx` étant son rang dans la série. */
export function pivotValueColor(dim: string, value: string, idx: number): string {
	if (dim === 'oa_voie') return oaStatusColor(value) ?? chartColor(idx);
	if (dim === 'oa_access') return oaStatusColor(OA_ACCESS_STATUS[value]) ?? chartColor(idx);
	if (dim === 'doc_type_grouped') return cssColor(docTypeGroupColorVar(value));
	if (dim === 'license') return cssColor(`license-${value}`) || chartColor(idx);
	return chartColor(idx);
}

/** Valeurs de `dim` présentes dans `rows`, dans leur ordre d'affichage. Sans ordre propre, par total décroissant. */
export function orderedPivotValues(dim: string, rows: Record<string, unknown>[]): string[] {
	const present = rows.map((r) => String(r[dim]));
	if (dim === 'year') return [...new Set(present)].sort((a, b) => Number(a) - Number(b));
	if (dim === 'oa_access') return OA_ACCESS_ORDER.filter((v) => present.includes(v));
	if (dim === 'oa_voie') return OA_VOIE_ORDER.filter((v) => present.includes(v));
	if (dim === 'license') return licenseOrder.filter((v) => present.includes(v));
	if (dim === 'doc_type_grouped') {
		// Famille « publications » éclatée en types fins, autres familles agrégées sous leur clé.
		const order = docTypeFamilies().flatMap((f) => (f.key === 'publications' ? f.types : [f.key]));
		return order.filter((k) => present.includes(k));
	}
	const totals = new Map<string, number>();
	for (const r of rows) {
		const v = String(r[dim]);
		totals.set(v, (totals.get(v) ?? 0) + Number(r.value ?? 0));
	}
	return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([v]) => v);
}
