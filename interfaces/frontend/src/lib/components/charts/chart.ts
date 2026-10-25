import { Chart, registerables } from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { cssVar } from './cssVar';

/**
 * Chart.js enregistré une fois pour toute l'application : composants standard, étiquettes de valeurs, police et couleur de texte lues dans les variables CSS.
 */
Chart.register(...registerables, ChartDataLabels);
Chart.defaults.font.family = cssVar('font');
Chart.defaults.color = cssVar('text-secondary');

export { Chart };
