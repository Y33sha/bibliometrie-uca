import { api } from "$lib/api";
import { confirmDialog } from "$lib/dialogs.svelte";
import { titleCase } from "$lib/utils";

/**
 * Confirmation avant fusion de deux personnes. Signale le nombre de publications
 * réattribuées (celles de la personne absorbée, `sourceId`) et le caractère
 * irréversible de l'action. Récupère le compte à jour depuis l'API pour rester
 * exact quel que soit le point d'appel.
 */
export async function confirmMerge(sourceId: number): Promise<boolean> {
  const p = await api<{ last_name: string; first_name: string; pub_count: number }>(
    `/api/persons/${sourceId}/curation`,
  );
  const name = `${titleCase(p.last_name)} ${titleCase(p.first_name)}`.trim();
  const n = p.pub_count ?? 0;
  const pubs =
    n === 1 ? "1 publication sera réattribuée" : `${n} publications seront réattribuées`;
  return confirmDialog({
    title: "Fusionner les personnes",
    message: `La personne « ${name} » sera absorbée puis supprimée — ${pubs} à la personne conservée. Cette action est irréversible.`,
    confirmLabel: "Fusionner",
    danger: true,
  });
}
