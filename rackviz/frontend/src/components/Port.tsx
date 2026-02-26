import React from 'react'
import type { Port as PortT } from '../types'

const U  = 44
const PW = 14
const PH = 14
const PG = 2

interface Props {
  port:        PortT
  x:           number
  y:           number
  onClick:     (p: PortT) => void
  editMode:    boolean
  showNumber?: boolean
  highlighted?: boolean    // search highlight
}

// Outer bezel color (surround)
function bezelColor(p: PortT): string {
  if (p.source_type === 'free')   return '#202020'
  if (p.port_type  === 'uplink')  return '#78350f'
  if (p.source_type === 'mc')     return p.mc_node_online ? '#14532d' : '#7f1d1d'
  return '#1e1b4b'  // manual / custom — dark indigo
}

// Status LED color
function ledColor(p: PortT): string {
  if (p.source_type === 'free')   return ''
  if (p.port_type  === 'uplink')  return '#f59e0b'
  if (p.source_type === 'mc')     return p.mc_node_online ? '#22c55e' : '#ef4444'
  return '#818cf8'  // manual
}

function portLabel(p: PortT): string {
  if (p.source_type === 'free') return `Порт ${p.port_number} — свободен`
  const name   = p.label || p.mc_node_name || p.manual_label || `Порт ${p.port_number}`
  const lines  = [`▪ ${name}`]
  if (p.source_type === 'mc')
    lines.push(p.mc_node_online ? '● Online' : '○ Offline')
  if (p.manual_ip)  lines.push(`IP: ${p.manual_ip}`)
  if (p.manual_mac) lines.push(`MAC: ${p.manual_mac}`)
  if (p.manual_type) lines.push(`Тип: ${p.manual_type}`)
  if (p.description) lines.push(`📝 ${p.description}`)
  return lines.join('\n')
}

export const PortCell: React.FC<Props> = ({
  port, x, y, onClick, editMode, showNumber, highlighted,
}) => {
  const isFree   = port.source_type === 'free'
  const isSFP    = port.port_type === 'sfp'
  const bevel    = bezelColor(port)
  const led      = ledColor(port)
  const cursor   = (editMode || !isFree) ? 'pointer' : 'default'
  const isUplink = port.port_type === 'uplink'

  return (
    <g
      style={{ cursor }}
      onClick={() => (editMode || !isFree) && onClick(port)}
    >
      <title>{portLabel(port)}</title>

      {/* Search highlight ring — pulsing yellow */}
      {highlighted && (
        <rect
          x={x - 3} y={y - 3} width={PW + 6} height={PH + 6}
          rx={4} fill="#fbbf2433" stroke="#fbbf24" strokeWidth={1.5}
        >
          <animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite" />
        </rect>
      )}

      {/* ── Outer bezel ─────────────────────────────────────────── */}
      <rect
        x={x} y={y} width={PW} height={PH}
        rx={2}
        fill={bevel}
        stroke={isFree ? '#111' : '#000'}
        strokeWidth={0.5}
      />

      {/* Top specular highlight on bezel */}
      <rect
        x={x + 1} y={y + 1} width={PW - 2} height={2}
        rx={1} fill="#ffffff0a"
      />

      {/* ── Inner socket opening (RJ45 / SFP) ───────────────────── */}
      {!isSFP ? (
        <>
          {/* Socket body — dark rectangular opening */}
          <rect
            x={x + 2} y={y + 2} width={PW - 4} height={PH - 6}
            rx={1} fill="#050505"
            stroke="#00000088" strokeWidth={0.3}
          />
          {/* Latch groove at bottom of socket */}
          <rect
            x={x + 4} y={y + PH - 4} width={PW - 8} height={2}
            rx={0.5} fill="#0a0a0a"
          />
          {/* Socket side guides */}
          <rect x={x + 2} y={y + PH - 5} width={1} height={3} fill="#111" />
          <rect x={x + PW - 3} y={y + PH - 5} width={1} height={3} fill="#111" />
        </>
      ) : (
        /* SFP cage — longer slot, different shape */
        <>
          <rect
            x={x + 1} y={y + 3} width={PW - 2} height={PH - 7}
            rx={1} fill="#050505"
          />
          <rect
            x={x + 1} y={y + 3} width={2} height={PH - 7}
            fill="#0f0f0f"
          />
        </>
      )}

      {/* Uplink marker: amber stripe across top */}
      {isUplink && (
        <rect x={x + 1} y={y + 1} width={PW - 2} height={3} rx={1} fill="#f59e0b55" />
      )}

      {/* ── Status LED (top-right of bezel) ─────────────────────── */}
      {!isFree && led && (
        <>
          <circle cx={x + PW - 2.5} cy={y + 2.5} r={1.8}
            fill={led} opacity={0.9}
          />
          {/* LED glow */}
          <circle cx={x + PW - 2.5} cy={y + 2.5} r={3}
            fill={led} opacity={0.15}
          />
        </>
      )}

      {/* Port number label below port (for patch panels) */}
      {showNumber && (
        <text
          x={x + PW / 2} y={y + PH + 7}
          textAnchor="middle"
          fill="#3a3a3a"
          fontSize={5.5}
          fontFamily="monospace"
        >
          {port.port_number}
        </text>
      )}
    </g>
  )
}

export { PW, PH, PG, U }
