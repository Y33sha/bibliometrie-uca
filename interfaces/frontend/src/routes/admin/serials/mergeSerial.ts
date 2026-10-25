import { ApiError, serials as serialsApi } from '#lib/api/index.js';
import { confirmDialog, toast } from '#lib/dialogs.svelte.js';

/**
 * Fusionne la revue `sourceId` dans `target` et rend `true` si la fusion a eu lieu.
 *
 * Les publications absorbées prennent le `serial_type` de la cible : quand ce changement requalifie des publications, leur nombre est annoncé et la fusion attend une confirmation.
 */
export async function mergeSerial(
	target: { id: number; serial_type?: string | null },
	sourceId: number
): Promise<boolean> {
	try {
		const impact = await serialsApi.typeChangeImpact(sourceId, target.serial_type || 'journal');
		if (impact.count > 0) {
			const plural = impact.count > 1 ? 's' : '';
			const msg = `Cette fusion entraînera un recalcul de la métadonnée « type de document » sur ${impact.count} publication${plural} de la publication en série absorbée. Continuer ?`;
			if (!(await confirmDialog({ message: msg, danger: true }))) return false;
		}
	} catch (e: any) {
		const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
		toast("Erreur lors du calcul d'impact : " + msg, 'error');
		return false;
	}
	try {
		await serialsApi.merge(target.id, sourceId);
		return true;
	} catch (e: any) {
		if (e instanceof ApiError) {
			const detail = (e.detail as { detail?: string })?.detail;
			toast(detail || `Erreur ${e.status}: ${JSON.stringify(e.detail)}`, 'error');
			return false;
		}
		toast('Erreur réseau : ' + e.message, 'error');
		return false;
	}
}
