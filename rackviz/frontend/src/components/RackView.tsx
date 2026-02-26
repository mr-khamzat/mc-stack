import React, { useRef, useState, useCallback } from 'react'
import type { RackDevice, Port as PortT, Callout } from '../types'
import { RackUnit, RACK_W, NUM_W } from './RackUnit'
import { U } from './Port'

interface Props {
  devices:                RackDevice[]
  editMode:               boolean
  calloutMode:            boolean
  callouts:               Callout[]
  highlightPortIds?:      Set<number>
  onPortClick:            (port: PortT, device: RackDevice) => void
  onMove?:                (deviceId: number, direction: 'up' | 'down') => void
  onReposition?:          (deviceId: number, rackUnit: number) => void
  onDeviceCalloutClick?:  (deviceId: number) => void
  onCalloutClick?:        (callout: Callout) => void
}

const RAIL_W    = 20
const FRAME_PAD = 10
const TOTAL_W   = RACK_W + NUM_W + FRAME_PAD * 2 + RAIL_W * 2

const devOffsetX = FRAME_PAD + RAIL_W   // 30
const devOffsetY = FRAME_PAD + 28       // 38

// ── Callout panel constants ──────────────────────────────────────────────────
const CALLOUT_PANEL_W = 230  // extra SVG width for callout bubbles
const CALLOUT_X       = TOTAL_W + 32  // left edge of callout bubble
const CALLOUT_W       = 180  // bubble width
const CALLOUT_MIN_GAP = 4

const CALLOUT_STYLE: Record<string, { bg: string; border: string; text: string }> = {
  yellow: { bg: '#1c1300', border: '#ca8a04', text: '#fef3c7' },
  blue:   { bg: '#0c1a33', border: '#3b82f6', text: '#bfdbfe' },
  red:    { bg: '#1a0505', border: '#dc2626', text: '#fecaca' },
  green:  { bg: '#051a0c', border: '#16a34a', text: '#bbf7d0' },
}

/** Simple word-wrap: split text into lines ≤ maxChars */
function wrapText(text: string, maxChars = 26): string[] {
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    if (paragraph.length <= maxChars) {
      lines.push(paragraph || ' ')
    } else {
      const words = paragraph.split(' ')
      let line = ''
      for (const word of words) {
        const candidate = line ? line + ' ' + word : word
        if (candidate.length <= maxChars) {
          line = candidate
        } else {
          if (line) lines.push(line)
          line = word.slice(0, maxChars)
        }
      }
      if (line) lines.push(line)
    }
  }
  return lines.length ? lines : [' ']
}

interface LayoutItem {
  callout:  Callout
  device:   RackDevice
  idealY:   number
  placedY:  number
  height:   number
  lines:    string[]
}

/** Layout callouts avoiding vertical overlaps */
function layoutCallouts(callouts: Callout[], devices: RackDevice[]): LayoutItem[] {
  const items: LayoutItem[] = []

  for (const callout of callouts) {
    const device = devices.find(d => d.id === callout.device_id)
    if (!device) continue
    const lines    = wrapText(callout.text)
    const height   = 12 + lines.length * 14 + 8
    const centerY  = devOffsetY + (device.rack_unit - 1) * U + device.unit_size * U / 2
    const idealY   = centerY - height / 2
    items.push({ callout, device, idealY, placedY: idealY, height, lines })
  }

  // Sort by ideal Y, then resolve overlaps greedily
  items.sort((a, b) => a.idealY - b.idealY)
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1]
    const minY = prev.placedY + prev.height + CALLOUT_MIN_GAP
    if (items[i].placedY < minY) items[i].placedY = minY
  }

  return items
}

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
  devices, editMode, calloutMode, callouts,
  highlightPortIds, onPortClick, onMove, onReposition,
  onDeviceCalloutClick, onCalloutClick,
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

  // Show callout panel when there are callouts OR we're in callout mode
  const showCalloutPanel = calloutMode || callouts.length > 0
  const svgW = showCalloutPanel ? TOTAL_W + CALLOUT_PANEL_W : TOTAL_W

  const calloutLayout = layoutCallouts(callouts, devices)

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
    const rect   = svgRef.current.getBoundingClientRect()
    const svgY   = e.clientY - rect.top
    const innerY = svgY - devOffsetY
    const targetUnit = Math.max(1, Math.min(totalUnits, Math.floor(innerY / U) + 1))
    setDrag(prev => prev ? { ...prev, currentUnit: targetUnit, mouseY: e.clientY } : null)
  }, [drag, totalUnits])

  const handleSVGMouseUp = useCallback(async () => {
    if (!drag) return
    const { deviceId, currentUnit } = drag
    setDrag(null)
    if (onReposition) onReposition(deviceId, currentUnit)
  }, [drag, onReposition])

  return (
    <div className="overflow-y-auto max-h-screen pb-4">
      <svg
        ref={svgRef}
        width={svgW}
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

        {/* Callout mode border */}
        {calloutMode && (
          <rect
            x={1} y={1} width={TOTAL_W - 2} height={svgH - 2}
            fill="none" rx={6}
            stroke="#a855f7"
            strokeWidth={1.5} strokeDasharray="8,4"
            opacity={0.45}
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

          {/* ── Callout mode: transparent hit areas over devices ─── */}
          {calloutMode && sorted.map(dev => {
            const hasCallout = callouts.some(c => c.device_id === dev.id)
            return (
              <g key={`co-hit-${dev.id}`}>
                <rect
                  x={NUM_W} y={(dev.rack_unit - 1) * U}
                  width={RACK_W - NUM_W} height={dev.unit_size * U}
                  fill={hasCallout ? '#a855f710' : 'transparent'}
                  stroke={hasCallout ? '#a855f740' : 'transparent'}
                  strokeWidth={1}
                  style={{ cursor: 'crosshair' }}
                  onClick={() => onDeviceCalloutClick?.(dev.id)}
                />
                {/* "+" icon for devices without callout */}
                {!hasCallout && (
                  <text
                    x={RACK_W - 20} y={(dev.rack_unit - 1) * U + dev.unit_size * U / 2 + 4}
                    textAnchor="middle" fill="#a855f755"
                    fontSize={14} fontFamily="monospace"
                    style={{ cursor: 'crosshair', pointerEvents: 'none' }}
                  >
                    +
                  </text>
                )}
              </g>
            )
          })}
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

        {/* Callout mode label */}
        {calloutMode && (
          <text
            x={leftRailX + RAIL_W + 6} y={devOffsetY + innerH - 6}
            fill="#a855f788"
            fontSize={8} fontFamily="monospace"
          >
            ● АННОТАЦИИ — кликни устройство чтобы добавить / изменить аннотацию
          </text>
        )}

        {/* ── Callout panel ───────────────────────────────────────── */}
        {showCalloutPanel && (
          <g>
            {/* Vertical guide line */}
            <line
              x1={TOTAL_W + 16} y1={devOffsetY}
              x2={TOTAL_W + 16} y2={devOffsetY + innerH}
              stroke="#2a2a2a" strokeWidth={1} strokeDasharray="3,5"
            />

            {/* Callout mode hint when no callouts yet */}
            {calloutMode && callouts.length === 0 && (
              <text
                x={CALLOUT_X + CALLOUT_W / 2} y={devOffsetY + innerH / 2}
                textAnchor="middle" fill="#4b5563"
                fontSize={9} fontFamily="monospace"
              >
                Кликни устройство →
              </text>
            )}

            {/* Render each callout bubble */}
            {calloutLayout.map(item => {
              const style    = CALLOUT_STYLE[item.callout.color] ?? CALLOUT_STYLE.yellow
              const bubbleY  = item.placedY
              const bubbleH  = item.height
              const centerY  = devOffsetY + (item.device.rack_unit - 1) * U + item.device.unit_size * U / 2
              const midBY    = bubbleY + bubbleH / 2

              // Bezier control points for connecting line
              const lineX1 = TOTAL_W - FRAME_PAD    // right frame edge
              const lineY1 = centerY
              const lineX2 = CALLOUT_X - 2           // triangle tip
              const lineY2 = midBY
              const cpX    = TOTAL_W + 14

              return (
                <g key={item.callout.id}>
                  {/* Connector line */}
                  <path
                    d={`M ${lineX1} ${lineY1} C ${cpX} ${lineY1} ${cpX} ${lineY2} ${lineX2} ${lineY2}`}
                    fill="none"
                    stroke={style.border}
                    strokeWidth={1.2}
                    strokeDasharray="4,3"
                    opacity={0.6}
                  />
                  {/* Dot on rack side */}
                  <circle
                    cx={lineX1} cy={lineY1}
                    r={2.5} fill={style.border} opacity={0.7}
                  />
                  {/* Triangle pointer */}
                  <path
                    d={`M ${CALLOUT_X - 1} ${midBY - 5} L ${CALLOUT_X + 7} ${midBY} L ${CALLOUT_X - 1} ${midBY + 5} Z`}
                    fill={style.border}
                    opacity={0.8}
                  />
                  {/* Bubble background */}
                  <rect
                    x={CALLOUT_X + 6} y={bubbleY}
                    width={CALLOUT_W} height={bubbleH}
                    rx={5}
                    fill={style.bg}
                    stroke={style.border}
                    strokeWidth={1}
                    style={{ cursor: calloutMode ? 'pointer' : 'default' }}
                    onClick={calloutMode ? () => onCalloutClick?.(item.callout) : undefined}
                  />
                  {/* Device name label */}
                  <text
                    x={CALLOUT_X + 14} y={bubbleY + 10}
                    fill={style.border}
                    fontSize={7} fontFamily="monospace" fontWeight="bold"
                    style={{ pointerEvents: 'none' }}
                  >
                    {item.device.name.length > 22
                      ? item.device.name.slice(0, 21) + '…'
                      : item.device.name}
                  </text>
                  {/* Separator line */}
                  <line
                    x1={CALLOUT_X + 10} y1={bubbleY + 13}
                    x2={CALLOUT_X + CALLOUT_W} y2={bubbleY + 13}
                    stroke={style.border} strokeWidth={0.4} opacity={0.4}
                  />
                  {/* Text lines */}
                  {item.lines.map((line, li) => (
                    <text
                      key={li}
                      x={CALLOUT_X + 14}
                      y={bubbleY + 23 + li * 14}
                      fill={style.text}
                      fontSize={10}
                      fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
                      style={{ pointerEvents: 'none' }}
                    >
                      {line}
                    </text>
                  ))}
                  {/* Edit hint in callout mode */}
                  {calloutMode && (
                    <text
                      x={CALLOUT_X + CALLOUT_W - 4} y={bubbleY + 10}
                      textAnchor="end" fill={style.border}
                      fontSize={7} fontFamily="monospace" opacity={0.6}
                      style={{ pointerEvents: 'none' }}
                    >
                      ✎
                    </text>
                  )}
                </g>
              )
            })}
          </g>
        )}
      </svg>
    </div>
  )
}
