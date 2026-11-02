type Neighbor = { cooccurrence_count: number; usage_count: number };

/** Spécificité de l'association : part des publications du sujet associé qui portent aussi le sujet de la page. */
export function specificity(neighbor: Neighbor): number {
  return Math.min(1, neighbor.cooccurrence_count / Math.max(neighbor.usage_count, 1));
}

/** Spécificité en pourcentage, arrondie à l'unité. */
export function specificityPercent(neighbor: Neighbor): number {
  return Math.round(specificity(neighbor) * 100);
}
