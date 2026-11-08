import { labListDefaults } from '#lib/labListDefaults.js';

/** Sélection à l'ouverture de la liste, servie par la configuration : le registre des filtres la lit à la création de la page. */
export const load = async () => ({ labDefaults: await labListDefaults() });
