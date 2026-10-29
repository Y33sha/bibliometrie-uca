import { describe, it, expect } from "vitest";
import { groupStructuresByType, structureGroupLabel } from "./structureTypes";

describe("groupStructuresByType", () => {
  it("place les types connus dans leur ordre, puis les autres par ordre alphabétique, en conservant l'ordre de chaque groupe", () => {
    const groups = groupStructuresByType([
      { id: 1, type: "labo" },
      { id: 2, type: "zeta" },
      { id: 3, type: "universite" },
      { id: 4, type: "labo" },
      { id: 5, type: "alpha" },
    ]);
    expect(groups.map(([type, list]) => [type, list.map((s) => s.id)])).toEqual([
      ["universite", [3]],
      ["labo", [1, 4]],
      ["alpha", [5]],
      ["zeta", [2]],
    ]);
  });
});

describe("structureGroupLabel", () => {
  it("renvoie le libellé d'un type connu, le code d'un type inconnu", () => {
    expect(structureGroupLabel("labo")).toBe("Laboratoires");
    expect(structureGroupLabel("inconnu")).toBe("inconnu");
  });
});
