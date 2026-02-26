import React from 'react'
import type { RackDevice, Port as PortT } from '../types'
import { PortCell, PW, PH, PG, U } from './Port'

const RACK_W     = 560
const NUM_W      = 28   // rack unit column
const PORT_START = 122  // x where ports begin

// Type indicator stripe color (left border)
const TYPE_COLOR: Record<string, string> = {
  patch_panel: '#a07850',
  switch:      '#1d6fce',
  hub:         '#7c3aed',
  router:      '#059669',
  server:      '#c0392b',
  poe_switch:  '#d97706',
  isp:         '#0891b2',
  auth_router: '#65a30d',
  other:       '#555555',
}

const TYPE_LABEL: Record<string, [string, string]> = {
  patch_panel: ['PP',   'Патч-панель'],
  switch:      ['SW',   'Коммутатор'],
  hub:         ['HUB',  'Хаб'],
  router:      ['RTR',  'Роутер'],
  server:      ['SRV',  'Сервер'],
  poe_switch:  ['PoE',  'PoE Switch'],
  isp:         ['ISP',  'ISP Switch'],
  auth_router: ['AUTH', 'Auth Router'],
  other:       ['?',    'Другое'],
}

// Background colors per device type
const TYPE_BG: Record<string, string> = {
  patch_panel: '#1a1510',
  switch:      '#0a1220',
  hub:         '#120d20',
  router:      '#071510',
  server:      '#150808',
  poe_switch:  '#160e00',
  isp:         '#001418',
  auth_router: '#0d1400',
  other:       '#141414',
}

// Group gap between port clusters
const GROUP_SIZE = 6
const GROUP_GAP  = 7

/** Calculate port x,y with group separators */
function portPos(
  idx:         number,
  isPP:        boolean,
  portsPerRow: number,
): { x: number; y: number } {
  const row = isPP
    ? (idx < portsPerRow ? 0 : 1)
    : Math.floor(idx / portsPerRow)
  const col = isPP
    ? (idx < portsPerRow ? idx : idx - portsPerRow)
    : idx % portsPerRow

  const group = Math.floor(col / GROUP_SIZE)
  const x     = col * (PW + PG) + group * GROUP_GAP
  const rowH  = isPP ? (PH + 4) : (PH + 3)
  const y     = row * rowH
  return { x, y }
}

/** Screw hole element at position (cx, cy) */
const ScrewHole: React.FC<{ cx: number; cy: number }> = ({ cx, cy }) => (
  <g>
    <circle cx={cx} cy={cy} r={4}
      fill="#0e0e0e" stroke="#2e2e2e" strokeWidth={0.6} />
    <circle cx={cx} cy={cy} r={2.5}
      fill="none" stroke="#383838" strokeWidth={0.4} />
    {/* Phillips crosshair */}
    <line x1={cx - 1.8} y1={cy} x2={cx + 1.8} y2={cy}
      stroke="#222" strokeWidth={0.7} />
    <line x1={cx} y1={cy - 1.8} x2={cx} y2={cy + 1.8}
      stroke="#222" strokeWidth={0.7} />
  </g>
)

interface Props {
  device:            RackDevice
  editMode:          boolean
  highlightPortIds?: Set<number>
  onPortClick:       (port: PortT, device: RackDevice) => void
  onMove?:           (id: number, dir: 'up' | 'down') => void
  onDragStart?:      (deviceId: number, e: React.MouseEvent) => void
  isFirst:           boolean
  isLast:            boolean
  isDragging?:       boolean
  dragY?:            number
  devOffsetY?:       number
}

export const RackUnit: React.FC<Props> = ({
  device, editMode, highlightPortIds,
  onPortClick, onMove, onDragStart,
  isFirst, isLast, isDragging, dragY, devOffsetY = 0,
}) => {
  const h   = device.unit_size * U
  // Use dragged Y if dragging, otherwise normal position
  const y   = isDragging && dragY !== undefined
    ? dragY - devOffsetY
    : (device.rack_unit - 1) * U

  const isPP     = device.device_type === 'patch_panel'
  const isSrv    = device.device_type === 'server'
  const isSwitch = ['switch', 'hub', 'poe_switch', 'isp'].includes(device.device_type)

  const portsPerRow = isPP
    ? Math.ceil(device.ports.length / 2)
    : Math.min(device.ports.length, 24)

  const typeColor = TYPE_COLOR[device.device_type] || '#555'
  const bgColor   = TYPE_BG[device.device_type] || '#141414'
  const [typeShort, typeFull] = TYPE_LABEL[device.device_type] || ['?', 'Другое']

  // Vertical centering for port block
  const rowCount = isPP
    ? 2
    : Math.ceil(device.ports.length / portsPerRow)
  const rowH        = isPP ? (PH + 4) : (PH + 3)
  const portsBlockH = rowCount * rowH - (isPP ? 4 : 3)
  const switchOffset = isSwitch ? 6 : 0
  const portOffsetY  = (h - portsBlockH - switchOffset) / 2 + switchOffset

  return (
    <g
      transform={`translate(0, ${y})`}
      opacity={isDragging ? 0.45 : 1}
    >
      {/* ── Device background ────────────────────────────────────── */}
      <rect
        x={NUM_W} y={1}
        width={RACK_W - NUM_W} height={h - 2}
        fill={bgColor} rx={2}
        stroke="#060606" strokeWidth={1}
      />

      {/* Fine horizontal brush lines on faceplate */}
      {Array.from({ length: Math.floor((h - 2) / 4) }).map((_, i) => (
        <line key={i}
          x1={NUM_W} y1={2 + i * 4} x2={RACK_W} y2={2 + i * 4}
          stroke="#ffffff03" strokeWidth={1}
        />
      ))}

      {/* Top specular line */}
      <line
        x1={NUM_W + 6} y1={2} x2={RACK_W - 2} y2={2}
        stroke="#ffffff09" strokeWidth={1}
      />

      {/* ── Left type-color stripe ───────────────────────────────── */}
      <rect
        x={NUM_W} y={1} width={5} height={h - 2}
        fill={typeColor}
      />
      <rect
        x={NUM_W} y={1} width={2} height={h - 2}
        fill="#ffffff20"
      />

      {/* ── U-number (rack frame column) ─────────────────────────── */}
      <text
        x={NUM_W - 4} y={h / 2 + 3.5}
        textAnchor="end" fill="#3a3a3a" fontSize={8} fontFamily="monospace"
      >
        {device.rack_unit}
      </text>

      {/* ── Type badge ───────────────────────────────────────────── */}
      <rect
        x={NUM_W + 7} y={h / 2 - 10}
        width={34} height={16} rx={3}
        fill={typeColor + '1a'}
        stroke={typeColor + '55'} strokeWidth={0.8}
      />
      <text
        x={NUM_W + 24} y={h / 2 + 2}
        textAnchor="middle"
        fill={typeColor}
        fontSize={8.5} fontFamily="monospace" fontWeight="bold"
      >
        {typeShort}
      </text>

      {/* ── Device name ──────────────────────────────────────────── */}
      <text
        x={NUM_W + 46}
        y={h / 2 - (h > 44 ? 6 : 3)}
        fill="#d0d0d0"
        fontSize={11} fontWeight="600"
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
        clipPath={`url(#clip-${device.id})`}
      >
        {device.name}
      </text>

      {/* ── Device type subtitle ─────────────────────────────────── */}
      <text
        x={NUM_W + 46}
        y={h / 2 + (h > 44 ? 8 : 10)}
        fill={typeColor + 'aa'}
        fontSize={7.5} fontFamily="monospace"
        clipPath={`url(#clip-${device.id})`}
      >
        {typeFull}{device.unit_size > 1 ? `  ·  ${device.unit_size}U  ·  ${device.port_count}p` : ''}
      </text>

      {/* ── Device notes (free-text annotation) ──────────────────── */}
      {device.notes && (
        <g>
          <rect
            x={NUM_W + 44} y={h - 14}
            width={Math.min(device.notes.length * 5.2 + 10, PORT_START - NUM_W - 56)}
            height={9} rx={2}
            fill="#ffffff08" stroke="#ffffff15" strokeWidth={0.4}
          />
          <text
            x={NUM_W + 49}
            y={h - 7}
            fill="#9ca3af"
            fontSize={6}
            fontStyle="italic"
            fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
            clipPath={`url(#clip-notes-${device.id})`}
          >
            {device.notes}
          </text>
        </g>
      )}

      {/* ── Mounting screws (Phillips) ───────────────────────────── */}
      <ScrewHole cx={NUM_W + 11} cy={Math.min(10, h / 2)} />
      <ScrewHole cx={RACK_W - 7}  cy={Math.min(10, h / 2)} />
      {h > 30 && (
        <>
          <ScrewHole cx={NUM_W + 11} cy={Math.max(h - 10, h / 2 + 4)} />
          <ScrewHole cx={RACK_W - 7}  cy={Math.max(h - 10, h / 2 + 4)} />
        </>
      )}

      {/* ── Patch panel: group background shading ────────────────── */}
      {isPP && Array.from({ length: Math.ceil(portsPerRow / GROUP_SIZE) }).map((_, gi) => {
        if (gi % 2 === 0) return null   // shade only odd groups
        const firstCol = gi * GROUP_SIZE
        if (firstCol >= portsPerRow) return null
        const colCount = Math.min(GROUP_SIZE, portsPerRow - firstCol)
        const { x: gx } = portPos(firstCol, true, portsPerRow)
        const gw = colCount * (PW + PG) + (colCount - 1) * 0 - PG + GROUP_GAP
        return (
          <rect key={gi}
            x={PORT_START + gx - 3} y={portOffsetY - 3}
            width={gw} height={portsBlockH + 6}
            rx={2} fill="#ffffff07"
          />
        )
      })}

      {/* ── Patch panel: cable management bar below ports ────────── */}
      {isPP && (
        <rect
          x={PORT_START - 2} y={portOffsetY + portsBlockH + 4}
          width={RACK_W - PORT_START - 10} height={4}
          rx={2} fill="#1a1a1a" stroke="#2a2a2a" strokeWidth={0.5}
        />
      )}

      {/* ── Server: drive bay slots ───────────────────────────────── */}
      {isSrv && (
        <g>
          {Array.from({ length: Math.min(8, Math.floor((RACK_W - PORT_START - 20) / 28)) }).map((_, i) => (
            <g key={i} transform={`translate(${PORT_START + i * 28}, ${h / 2 - 10})`}>
              <rect width={24} height={20} rx={2}
                fill="#0a0a0a" stroke="#2a2a2a" strokeWidth={0.6} />
              {/* Drive activity LED */}
              <circle cx={20} cy={3} r={1.5}
                fill={i < 2 ? '#f59e0b' : '#1a1a1a'}
                opacity={0.8}
              />
              {/* Drive slot lines */}
              <rect x={2} y={6} width={16} height={2} rx={0.5} fill="#1a1a1a" />
              <rect x={2} y={10} width={16} height={2} rx={0.5} fill="#1a1a1a" />
              <rect x={2} y={14} width={16} height={2} rx={0.5} fill="#1a1a1a" />
            </g>
          ))}
          {/* Power LED */}
          <circle cx={RACK_W - 18} cy={h / 2} r={4}
            fill="#001400" stroke="#166534" strokeWidth={0.8} />
          <circle cx={RACK_W - 18} cy={h / 2} r={2.5}
            fill="#22c55e" opacity={0.9} />
          <circle cx={RACK_W - 18} cy={h / 2} r={4}
            fill="#22c55e" opacity={0.08} />
          {/* USB port */}
          <rect x={RACK_W - 32} y={h / 2 - 4} width={10} height={8}
            rx={1} fill="#080808" stroke="#222" strokeWidth={0.5} />
        </g>
      )}

      {/* ── Switch/Hub: status LEDs above ports ──────────────────── */}
      {isSwitch && (
        <g transform={`translate(${PORT_START}, ${portOffsetY - switchOffset})`}>
          {device.ports.slice(0, portsPerRow).map((port, i) => {
            const group = Math.floor(i / GROUP_SIZE)
            const lx    = i * (PW + PG) + group * GROUP_GAP + PW / 2
            const isOn  = port.source_type !== 'free'
            const isOnline = port.mc_node_online
            return (
              <g key={port.id}>
                {/* LED body */}
                <rect x={lx - 2} y={0} width={4} height={3}
                  rx={0.5} fill={isOn ? (isOnline ? '#052e16' : '#450a0a') : '#111'}
                  stroke="#0a0a0a" strokeWidth={0.3}
                />
                {/* LED glow dot */}
                <circle cx={lx} cy={1.5} r={1.2}
                  fill={isOn ? (isOnline ? '#22c55e' : '#ef4444') : '#1a1a1a'}
                  opacity={0.9}
                />
              </g>
            )
          })}
        </g>
      )}

      {/* ── Ports ────────────────────────────────────────────────── */}
      <g transform={`translate(${PORT_START}, ${portOffsetY})`}>
        {device.ports.map((port, i) => {
          const { x: px, y: py } = portPos(i, isPP, portsPerRow)
          return (
            <PortCell
              key={port.id}
              port={port}
              x={px} y={py}
              editMode={editMode}
              highlighted={highlightPortIds?.has(port.id)}
              onClick={(p) => onPortClick(p, device)}
              showNumber={isPP}
            />
          )
        })}

        {/* Patch panel: group number markers */}
        {isPP && portsPerRow > 0 && Array.from({
          length: Math.ceil(portsPerRow / GROUP_SIZE),
        }).map((_, gi) => {
          const firstInGroup = gi * GROUP_SIZE
          if (firstInGroup >= portsPerRow) return null
          const { x: gx } = portPos(firstInGroup, true, portsPerRow)
          return (
            <text key={gi}
              x={gx} y={-4}
              fill="#383838" fontSize={5.5} fontFamily="monospace"
            >
              {firstInGroup + 1}
            </text>
          )
        })}
      </g>

      {/* ── Edit mode: ▲▼ move buttons (only when not drag mode) ──── */}
      {editMode && onMove && (
        <>
          {!isFirst && (
            <g
              onClick={(e) => { e.stopPropagation(); onMove(device.id, 'up') }}
              style={{ cursor: 'pointer' }}
            >
              <rect x={RACK_W - 46} y={4} width={19} height={15} rx={3}
                fill="#ffffff12" stroke="#ffffff22" strokeWidth={0.5} />
              <text x={RACK_W - 36.5} y={14.5}
                textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="monospace">▲</text>
            </g>
          )}
          {!isLast && (
            <g
              onClick={(e) => { e.stopPropagation(); onMove(device.id, 'down') }}
              style={{ cursor: 'pointer' }}
            >
              <rect x={RACK_W - 25} y={4} width={19} height={15} rx={3}
                fill="#ffffff12" stroke="#ffffff22" strokeWidth={0.5} />
              <text x={RACK_W - 15.5} y={14.5}
                textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="monospace">▼</text>
            </g>
          )}
        </>
      )}

      {/* ── Drag handle (edit mode) ───────────────────────────────── */}
      {editMode && onDragStart && (
        <g
          style={{ cursor: 'grab' }}
          onMouseDown={(e) => { e.stopPropagation(); onDragStart(device.id, e) }}
        >
          <rect x={RACK_W - 70} y={h / 2 - 8} width={16} height={16} rx={3}
            fill="#ffffff08" stroke="#ffffff18" strokeWidth={0.5} />
          {/* Drag dots */}
          {[0, 3, 6].map(dy => (
            [0, 4].map(dx => (
              <circle key={`${dx}-${dy}`}
                cx={RACK_W - 66 + dx} cy={h / 2 - 4 + dy}
                r={0.8} fill="#555"
              />
            ))
          ))}
        </g>
      )}

      {/* ── Bottom separator ─────────────────────────────────────── */}
      <line
        x1={NUM_W} y1={h - 1} x2={RACK_W} y2={h - 1}
        stroke="#060606" strokeWidth={1}
      />

      <defs>
        <clipPath id={`clip-${device.id}`}>
          <rect x={0} y={0} width={PORT_START - NUM_W - 50} height={h} />
        </clipPath>
        <clipPath id={`clip-notes-${device.id}`}>
          <rect x={0} y={0} width={PORT_START - NUM_W - 56} height={h} />
        </clipPath>
      </defs>
    </g>
  )
}

export { RACK_W, NUM_W, PORT_START, GROUP_SIZE, GROUP_GAP }
