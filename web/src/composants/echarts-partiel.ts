// Import partiel d'ECharts (Sankey + infobulle + rendu canvas) : seul ce module est chargé à la demande.
import { SankeyChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([SankeyChart, TooltipComponent, CanvasRenderer])

export { init }
