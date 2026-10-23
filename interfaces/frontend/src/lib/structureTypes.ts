/**
 * Source unique des types de structure (valeur enum + libellé). Aligné sur l'enum Postgres `structure_type` / `StructureType` (domaine).
 */
export const STRUCTURE_TYPES: readonly { value: string; label: string }[] = [
  { value: "labo", label: "Laboratoire" },
  { value: "equipe", label: "Équipe" },
  { value: "universite", label: "Université" },
  { value: "ecole", label: "École" },
  { value: "chu", label: "CHU" },
  { value: "onr", label: "ONR" },
  { value: "site", label: "Site" },
  { value: "admin", label: "Administration" },
  { value: "autre", label: "Autre" },
];

/** Libellés des groupes de structures dans les listes déroulantes, dans leur ordre d'affichage. */
export const STRUCTURE_GROUP_LABELS: Readonly<Record<string, string>> = {
  universite: "Universités",
  onr: "Organismes de recherche",
  chu: "CHU",
  ecole: "Écoles",
  labo: "Laboratoires",
  equipe: "Équipes",
  admin: "Administrations",
  autre: "Autres",
  site: "Sites",
};

/** Libellé du groupe d'un type de structure, ou son code si le type est absent de `STRUCTURE_GROUP_LABELS`. */
export function structureGroupLabel(type: string): string {
  return STRUCTURE_GROUP_LABELS[type] ?? type;
}

/** Structures groupées par type. Les types de `STRUCTURE_GROUP_LABELS` viennent d'abord, dans leur ordre, puis les autres par ordre alphabétique. Chaque groupe conserve l'ordre de la liste reçue. */
export function groupStructuresByType<T extends { type: string }>(structures: readonly T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const s of structures) {
    const group = groups.get(s.type);
    if (group) group.push(s);
    else groups.set(s.type, [s]);
  }
  const known = Object.keys(STRUCTURE_GROUP_LABELS).filter((t) => groups.has(t));
  const others = [...groups.keys()].filter((t) => !(t in STRUCTURE_GROUP_LABELS)).sort();
  return [...known, ...others].map((t) => [t, groups.get(t)!]);
}
