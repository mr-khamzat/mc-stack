import React, { useRef, useState, useCallback } from 'react'
import type { RackDevice, Port as PortT } from '../types'
import { RackUnit, RACK_W, NUM_W } from './RackUnit'
import { U, PW, PH, PG } from './Port'

interface Props {
  devices:           RackDevice[]
  editMode:          boolean
  highlightPortIds?: Set<number>
  onPortClick:       (port: PortT, device: RackDevice) => void
  onMove?:           (deviceId: number, direction: 'up' | 'down') => void
  onReposition?:     (deviceId: number, rackUnit: number) => void
}

const RAIL_W    = 20
const FRAME_PAD = 10
const TOTAL_W   = RACK_W + NUM_W + FRAME_PAD * 2 + RAIL_W * 2

const devOffsetX = FRAME_PAD + RAIL_W   // 30
const devOffsetY = FRAME_PAD + 28       // 38

// Legend items
const LEGEND = [
  { color: '#202020', label: 'Свободен' },
  { color: '#14532d', label: 'MC Online' },
  { color: '#7f1d1d', label: 'MC Offline' },
  { color: '#1e1b4b', label: 'Ручное' },
  { color: '#78350f', label: 'Uplink' },
]

interface DragState {
  deviceId:      number
  deviceSize:    number
  startRackUnit: number
  currentUnit:   number
  mouseY:        number
}

export const RackView: React.FC<Props> = ({
  devices, editMode, highlightPortIds,
  onPortClick, onMove, onReposition,
}) => {
  const svgRef = useRef<SVGSVGElement>(null)
  const [drag, setDrag] = useState<DragState | null>(null)

  if (!devices.length) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        Загрузка стойки…
      </div>
    )
  }

  const sorted     = [...devices].sort((a, b) => a.rack_unit - b.rack_unit)
  const lastDev    = sorted[sorted.length - 1]
  const totalUnits = lastDev.rack_unit + lastDev.unit_size - 1
  const innerH     = totalUnits * U
  const svgH       = innerH + FRAME_PAD * 2 + 28

  const leftRailX  = FRAME_PAD
  const rightRailX = TOTAL_W - FRAME_PAD - RAIL_W

  // ── DnD handlers ──────────────────────────────────────────────────────────
  const handleDeviceDragStart = useCallback((deviceId: number, e: React.MouseEvent) => {
    if (!editMode) return
    const device = devices.find(d => d.id === deviceId)
    if (!device) return
    e.preventDefault()
    setDrag({
      deviceId,
      deviceSize: device.unit_size,
      startRackUnit: device.rack_unit,
      currentUnit: device.rack_unit,
      mouseY: e.clientY,
    })
  }, [editMode, devices])

  const handleSVGMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!drag || !svgRef.current) return
    const rect  = svgRef.current.getBoundingClientRect()
    const svgY  = e.clientY - rect.top
    const innerY = svgY - devOffsetY
    const targetUnit = Math.max(1, Math.min(totalUnits, Math.floor(innerY / U) + 1))
    setDrag(prev => prev ? { ...prev, currentUnit: targetUnit, mouseY: e.clientY } : null)
  }, [drag, totalUnits])

  const handleSVGMouseUp = useCallback(async () => {
    if (!drag) return
    const { deviceId, currentUnit } = drag
    setDrag(null)
    if (onReposition) {
      onReposition(deviceId, currentUnit)
    }
  }, [drag, onReposition])

  return (
    <div className="overflow-y-auto max-h-screen pb-4">
      <svg
        ref={svgRef}
        width={TOTAL_W}
        height={svgH}
        style={{ fontFamily: 'monospace', display: 'block', userSelect: 'none' }}
        xmlns="http://www.w3.org/2000/svg"
        onMouseMove={drag ? handleSVGMouseMove : undefined}
        onMouseUp={drag ? handleSVGMouseUp : undefined}
        onMouseLeave={drag ? handleSVGMouseUp : undefined}
      >
        <defs>
          <linearGradient id="railGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%"   stopColor="#252525" />
            <stop offset="30%"  stopColor="#1a1a1a" />
            <stop offset="70%"  stopColor="#222222" />
            <stop offset="100%" stopColor="#2a2a2a" />
          </linearGradient>
          <linearGradient id="frameGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="#1c1c1c" />
            <stop offset="100%" stopColor="#0e0e0e" />
          </linearGradient>
        </defs>

        {/* ── Outer frame ────────────────────────────────────────── */}
        <rect
          x={0} y={0} width={TOTAL_W} height={svgH}
          fill="url(#frameGrad)" rx={6}
          stroke="#2e2e2e" strokeWidth={2}
        />
        <rect
          x={2} y={2} width={TOTAL_W - 4} height={svgH - 4}
          fill="none" rx={5}
          stroke="#363636" strokeWidth={0.5}
        />

        {/* ── Rack brand bar ─────────────────────────────────────── */}
        <rect
          x={leftRailX + RAIL_W} y={FRAME_PAD}
          width={TOTAL_W - FRAME_PAD * 2 - RAIL_W * 2} height={24}
          fill="#0f0f0f" rx={2}
          stroke="#252525" strokeWidth={0.5}
        />
        <text
          x={leftRailX + RAIL_W + 10} y={FRAME_PAD + 15}
          fill="#333" fontSize={9} fontFamily="monospace" fontWeight="bold"
          letterSpacing="3"
        >
          SERVER RACK
        </text>
        <text
          x={rightRailX - 6} y={FRAME_PAD + 15}
          textAnchor="end" fill="#282828" fontSize={8} fontFamily="monospace"
        >
          {totalUnits}U
        </text>

        {/* Edit mode border */}
        {editMode && (
          <rect
            x={1} y={1} width={TOTAL_W - 2} height={svgH - 2}
            fill="none" rx={6}
            stroke="#f59e0b"
            strokeWidth={1.5} strokeDasharray="10,5"
            opacity={0.4}
          />
        )}

        {/* ── Left rail ──────────────────────────────────────────── */}
        <rect
          x={leftRailX} y={FRAME_PAD + 24}
          width={RAIL_W} height={innerH + 4}
          fill="url(#railGrad)" rx={2}
          stroke="#2a2a2a" strokeWidth={0.5}
        />
        {/* ── Right rail ─────────────────────────────────────────── */}
        <rect
          x={rightRailX} y={FRAME_PAD + 24}
          width={RAIL_W} height={innerH + 4}
          fill="url(#railGrad)" rx={2}
          stroke="#2a2a2a" strokeWidth={0.5}
        />

        {/* ── U markings + screw holes on rails ──────────────────── */}
        {Array.from({ length: totalUnits }).map((_, i) => {
          const uy = devOffsetY + i * U
          return (
            <g key={i}>
              <circle cx={leftRailX + RAIL_W / 2} cy={uy + 5}
                r={3} fill="#0a0a0a" stroke="#333" strokeWidth={0.5} />
              <circle cx={leftRailX + RAIL_W / 2} cy={uy + U - 5}
                r={3} fill="#0a0a0a" stroke="#333" strokeWidth={0.5} />
              <text
                x={leftRailX + RAIL_W / 2} y={uy + U / 2 + 3}
                textAnchor="middle" fill="#353535"
                fontSize={6.5} fontFamily="monospace"
              >
                {i + 1}
              </text>

              <circle cx={rightRailX + RAIL_W / 2} cy={uy + 5}
                r={3} fill="#0a0a0a" stroke="#333" strokeWidth={0.5} />
              <circle cx={rightRailX + RAIL_W / 2} cy={uy + U - 5}
                r={3} fill="#0a0a0a" stroke="#333" strokeWidth={0.5} />
              <text
                x={rightRailX + RAIL_W / 2} y={uy + U / 2 + 3}
                textAnchor="middle" fill="#353535"
                fontSize={6.5} fontFamily="monospace"
              >
                {i + 1}
              </text>

              <line
                x1={leftRailX + RAIL_W} y1={uy}
                x2={rightRailX} y2={uy}
                stroke="#0c0c0c" strokeWidth={0.5} opacity={0.5}
              />
            </g>
          )
        })}

        {/* ── Device background panel ─────────────────────────────── */}
        <rect
          x={leftRailX + RAIL_W} y={devOffsetY}
          width={RACK_W} height={innerH}
          fill="#0f0f0f"
        />

        {/* ── Drag drop target indicator ───────────────────────────── */}
        {drag && (
          <rect
            x={devOffsetX + NUM_W} y={devOffsetY + (drag.currentUnit - 1) * U}
            width={RACK_W - NUM_W} height={drag.deviceSize * U}
            fill="#3b82f610" stroke="#3b82f6" strokeWidth={1}
            strokeDasharray="6,3" rx={2}
          />
        )}

        {/* ── Devices ─────────────────────────────────────────────── */}
        <g transform={`translate(${devOffsetX}, ${devOffsetY})`}>
          {sorted.map((dev, idx) => (
            <RackUnit
              key={dev.id}
              device={dev}
              editMode={editMode}
              highlightPortIds={highlightPortIds}
              onPortClick={onPortClick}
              onMove={onMove}
              onDragStart={editMode ? handleDeviceDragStart : undefined}
              isFirst={idx === 0}
              isLast={idx === sorted.length - 1}
              isDragging={drag?.deviceId === dev.id}
              devOffsetY={devOffsetY}
            />
          ))}
        </g>

        {/* ── Legend ─────────────────────────────────────────────── */}
        <g transform={`translate(${TOTAL_W - 115}, ${svgH - 68})`}>
          <rect x={0} y={0} width={108} height={62} rx={4}
            fill="#00000099" stroke="#252525" strokeWidth={0.5} />
          {LEGEND.map(({ color, label }, i) => (
            <g key={i} transform={`translate(6, ${6 + i * 11})`}>
              <rect width={9} height={9} rx={2} fill={color}
                stroke="#0a0a0a" strokeWidth={0.5} />
              <text x={14} y={8} fill="#555" fontSize={7.5}>
                {label}
              </text>
            </g>
          ))}
        </g>

        {/* Edit mode label */}
        {editMode && (
          <text
            x={leftRailX + RAIL_W + 6} y={devOffsetY + innerH - 6}
            fill="#f59e0b88"
            fontSize={8} fontFamily="monospace"
          >
            ● EDIT MODE — кликни порт для назначения · ▲▼ или тащи ⠿ для перемещения
          </text>
        )}
      </svg>
    </div>
  )
}
