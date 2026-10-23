import { describe, it, expect } from "vitest";
import { compareStructureLabels, structsTooltip, type Affiliation, type StructInfo } from "./structureLabels";

const struct = (over: Partial<StructInfo>): StructInfo =>
  ({ id: 1, name: "Laboratoire", acronym: "LAB", type: "labo", ...over }) as StructInfo;

const contribution = (over: Partial<Affiliation>): Affiliation => ({
  raw_affiliation: null,
  structure_ids: [],
  ...over,
});

describe("structsTooltip", () => {
  it("assemble l'affiliation brute et les structures identifiées", () => {
    const out = structsTooltip(
      contribution({ raw_affiliation: "Université Clermont Auvergne", structure_ids: [1] }),
      { "1": struct({ acronym: "LMBP" }) },
    );
    expect(out).toBe("Université Clermont Auvergne\nStructures identifiées\u00a0: LMBP");
  });

  it("ne produit aucun balisage HTML autour d'une affiliation malveillante (non-régression XSS)", () => {
    // L'affiliation brute vient des sources externes : le tooltip la rend en texte,
    // la fonction ne doit introduire aucune balise autour d'elle.
    const payload = '<img src=x onerror="alert(1)">';
    const out = structsTooltip(contribution({ raw_affiliation: payload }), {});
    // La charge utile ressort telle quelle (elle sera affichée comme texte par Tooltip),
    // sans balise ajoutée par la fonction (pas de <em>, pas de <br>).
    expect(out).toBe(payload);
    expect(out).not.toContain("<em>");
    expect(out).not.toContain("<br>");
  });
});

describe("compareStructureLabels", () => {
  it("trie sur l'acronyme, à défaut le nom, sans tenir compte de la casse ni des accents", () => {
    const sorted = [
      { acronym: "LMBP", name: "Laboratoire de mathématiques" },
      { acronym: null, name: "équipe Gamma" },
      { acronym: "ICCF", name: "Institut de chimie" },
      { acronym: "cerdi", name: "Centre d'études" },
    ].sort(compareStructureLabels);
    expect(sorted.map((s) => s.acronym || s.name)).toEqual(["cerdi", "équipe Gamma", "ICCF", "LMBP"]);
  });
});
