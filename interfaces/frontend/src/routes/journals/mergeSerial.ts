import { errorMessage, serials as serialsApi } from '#lib/api/index.js';
import { confirmDialog, toast } from '#lib/dialogs.svelte.js';

/**
 * Fusionne la revue `sourceId` dans `target` et renvoie `true` si la fusion a eu lieu.
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
	} catch (e) {
		toast("Erreur lors du calcul d'impact : " + errorMessage(e), 'error');
		return false;
	}
	try {
		await serialsApi.merge(target.id, sourceId);
		return true;
	} catch (e) {
		toast(errorMessage(e), 'error');
		return false;
	}
}
