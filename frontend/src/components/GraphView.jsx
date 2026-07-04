import { useEffect, useRef } from 'react'
import { Network } from 'vis-network'
import { DataSet } from 'vis-data'

export const GROUP_COLORS = {
  Material: '#00A9E0',
  Process: '#2ED573',
  Equipment: '#FFB020',
  Parameter: '#C792EA',
  Condition: '#FF7A9E',
  Experiment: '#8899AA',
}

export const GROUP_RU = {
  Material: 'материал',
  Process: 'процесс',
  Equipment: 'оборудование',
  Parameter: 'параметр',
  Condition: 'условие',
  Experiment: 'эксперимент',
}

export default function GraphView({ graph, height = 420, physics = true, onNodeClick }) {
  const ref = useRef(null)
  const clickRef = useRef(onNodeClick)

  useEffect(() => {
    clickRef.current = onNodeClick
  }, [onNodeClick])

  useEffect(() => {
    if (!ref.current || !graph?.nodes?.length) return
    const nodes = new DataSet(
      graph.nodes.map((n) => ({
        ...n,
        shape: 'dot',
        size: 13,
        color: {
          background: GROUP_COLORS[n.group] || '#8899AA',
          border: '#FFFFFF',
          highlight: { background: '#fff', border: GROUP_COLORS[n.group] || '#8899AA' },
        },
        font: { size: 11.5, color: '#33506B', strokeWidth: 0 },
      })),
    )
    const edges = new DataSet(
      graph.edges.map((e, i) => ({
        id: i,
        ...e,
        arrows: { to: { scaleFactor: 0.5 } },
        color: { color: '#B9CCDE', highlight: '#0077C8' },
        font: { size: 8.5, color: '#7B93A8', align: 'middle', strokeWidth: 0 },
        width: 1.2,
      })),
    )
    const net = new Network(
      ref.current,
      { nodes, edges },
      {
        physics: physics
          ? { stabilization: { iterations: 120 }, barnesHut: { gravitationalConstant: -3200, springLength: 130 } }
          : false,
        interaction: { hover: true, tooltipDelay: 120 },
      },
    )
    net.on('click', (params) => {
      if (!clickRef.current) return
      const id = params.nodes?.[0]
      if (id === undefined) return
      const node = nodes.get(id)
      if (node) clickRef.current(node.label || String(id), node.group)
    })
    return () => net.destroy()
  }, [graph, physics])

  const groups = [...new Set((graph?.nodes || []).map((n) => n.group))]

  if (!graph?.nodes?.length) {
    return (
      <div
        className="grid place-items-center text-center text-sm text-nn-muted border border-dashed border-nn-border rounded-xl"
        style={{ height }}
      >
        Нет данных графа для этого запроса.
        <br />
        Запустите Neo4j + Stage 4 для визуализации.
      </div>
    )
  }

  return (
    <div>
      <div ref={ref} style={{ height }} className="rounded-xl bg-nn-panel2/40" />
      <div className="flex flex-wrap gap-3 mt-2.5 text-[11px] text-nn-muted">
        {groups.map((g) => (
          <span key={g} className="inline-flex items-center gap-1.5">
            <i
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: GROUP_COLORS[g] || '#8899AA' }}
            />
            {GROUP_RU[g] || g}
          </span>
        ))}
      </div>
    </div>
  )
}
