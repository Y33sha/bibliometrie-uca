import iso from 'i18n-iso-countries';
import frLocale from 'i18n-iso-countries/langs/fr.json';

iso.registerLocale(frLocale);

/** Nom français d'un pays, d'après son code ISO 3166-1 alpha-2 (casse indifférente). */
export function countryName(alpha2: string): string | undefined {
	return iso.getName(alpha2.toUpperCase(), 'fr');
}
