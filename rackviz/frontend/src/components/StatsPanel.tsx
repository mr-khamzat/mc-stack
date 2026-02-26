import React from 'react'
import type { RackDevice } from '../types'

interface Props {
  devices: RackDevice[]
  onClose: () => void
}

export const StatsPanel: React.FC<Props> = ({ devices, onClose }) => {
  const sorted = [...devices].sort((a, b) => a.rack_unit - b.rack_unit)

  const totalPorts    = devices.reduce((s, d) => s + d.ports.length, 0)
  const occupiedPorts = devices.reduce((s, d) => s + d.ports.filter(p => p.source_type !== 'free').length, 0)
  const freePorts     = totalPorts - occupiedPorts
  const mcPorts       = devices.reduce((s, d) => s + d.ports.filter(p => p.source_type === 'mc').length, 0)
  const manualPorts   = devices.reduce((s, d) => s + d.ports.filter(p => p.source_type === 'manual' || p.source_type === 'custom').length, 0)
  const fillPct       = totalPorts > 0 ? Math.round(occupiedPorts / totalPorts * 100) : 0

  const fillColor = fillPct >= 90 ? '#ef4444' : fillPct >= 70 ? '#f59e0b' : '#22c55e'

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end p-4 pointer-events-none"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg shadow-2xl w-80 pointer-events-auto"
        style={{ marginTop: '52px' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <span className="text-base">📊</span>
            <span className="text-white font-semibold text-sm">Статистика стойки</span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white text-lg leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Summary */}
          <div>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>Заполнение</span>
              <span style={{ color: fillColor }}>{fillPct}%</span>
            </div>
            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${fillPct}%`, background: fillColor }}
              />
            </div>
          </div>

          {/* Totals grid */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'Всего',    value: totalPorts,    color: '#9ca3af' },
              { label: 'Занято',   value: occupiedPorts, color: '#f59e0b' },
              { label: 'Свободно', value: freePorts,     color: '#22c55e' },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-gray-800 rounded-lg p-2 text-center">
                <div className="text-lg font-bold" style={{ color }}>{value}</div>
                <div className="text-xs text-gray-500">{label}</div>
              </div>
            ))}
          </div>

          {/* Port types */}
          <div className="flex gap-2 text-xs">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block bg-green-500" />
              <span className="text-gray-400">MC онлайн: </span>
              <span className="text-white">{devices.reduce((s, d) => s + d.ports.filter(p => p.source_type === 'mc' && p.mc_node_online).length, 0)}</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block bg-red-500" />
              <span className="text-gray-400">MC офлайн: </span>
              <span className="text-white">{devices.reduce((s, d) => s + d.ports.filter(p => p.source_type === 'mc' && !p.mc_node_online).length, 0)}</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block bg-indigo-400" />
              <span className="text-gray-400">Ручных: </span>
              <span className="text-white">{manualPorts}</span>
            </span>
          </div>

          {/* Per-device breakdown */}
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">По устройствам</div>
            <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
              {sorted.map(dev => {
                const total    = dev.ports.length
                const occupied = dev.ports.filter(p => p.source_type !== 'free').length
                const free     = total - occupied
                const pct      = total > 0 ? Math.round(occupied / total * 100) : 0
                const devColor = pct >= 90 ? '#ef4444' : pct >= 70 ? '#f59e0b' : '#22c55e'
                return (
                  <div key={dev.id} className="bg-gray-800 rounded px-2.5 py-1.5">
                    <div className="flex justify-between items-baseline mb-1">
                      <span className="text-gray-200 text-xs truncate max-w-[140px]" title={dev.name}>
                        {dev.name}
                      </span>
                      <span className="text-xs ml-2 shrink-0" style={{ color: devColor }}>
                        {occupied}/{total}
                      </span>
                    </div>
                    <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, background: devColor }}
                      />
                    </div>
                    <div className="flex justify-between text-gray-600 text-xs mt-0.5">
                      <span>{free} своб.</span>
                      <span>{pct}%</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
