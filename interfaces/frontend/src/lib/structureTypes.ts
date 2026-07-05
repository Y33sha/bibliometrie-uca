/**
 * Source unique des types de structure (valeur enum + libellé), partagée par les pages qui
 * proposent de choisir un type : l'admin des structures (formulaire, filtre) et la config de
 * l'affichage public. Aligné sur l'enum Postgres `structure_type` / `StructureType` (domaine).
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
