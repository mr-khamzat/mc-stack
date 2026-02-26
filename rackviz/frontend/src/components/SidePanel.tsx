import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Port, RackDevice } from '../types'

interface Props {
  port:     Port
  device:   RackDevice
  onClose:  () => void
  editMode: boolean
  onEdit:   () => void
}

function InfoRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return (
    <div className="flex gap-2 py-0.5 border-b border-gray-800">
      <span className="text-gray-500 text-xs w-28 shrink-0">{label}</span>
      <span className="text-gray-200 text-xs break-all">{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1 mt-2">{title}</div>
      {children}
    </div>
  )
}

function MCDetails({ nodeId }: { nodeId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['node', nodeId],
    queryFn:  () => api.get('/mc/node/public', { params: { id: nodeId } }).then(r => r.data),
    staleTime: 30_000,
    retry: 1,
  })

  if (isLoading) return <div className="text-gray-500 text-xs py-2">Загрузка данных из MeshCentral…</div>
  if (isError)   return <div className="text-red-400 text-xs py-2">Нет данных от MeshCentral</div>
  if (!data)     return null

  const g = data.General || {}
  const os = data['Operating System'] || {}
  const hw = data.Hardware || {}
  const net = data.Networking || {}
  const agent = data['Mesh Agent'] || {}

  const avList = Array.isArray(g.AntiVirus) ? g.AntiVirus.join(', ') : g.AntiVirus

  return (
    <>
      <Section title="Общее">
        <InfoRow label="Имя"          value={g['Server Name'] || g['Computer Name']} />
        <InfoRow label="IP (LAN)"     value={g['IP Address']} />
        <InfoRow label="Антивирус"    value={avList} />
        <InfoRow label="Статус агента" value={agent['Agent status']} />
        <InfoRow label="Последний IP" value={agent['Last agent address']} />
      </Section>

      <Section title="Операционная система">
        <InfoRow label="ОС"           value={os.Version || os.Name} />
        <InfoRow label="Архитектура"  value={os.Architecture} />
      </Section>

      {hw && Object.keys(hw).length > 0 && (
        <Section title="Железо">
          {Object.entries(hw).map(([k, v]) => (
            <InfoRow key={k} label={k} value={String(v)} />
          ))}
        </Section>
      )}

      {Object.keys(net).length > 0 && (
        <Section title="Сеть">
          {Object.entries(net).slice(0, 3).map(([iface, info]) => {
            const ipv4 = typeof info === 'object' && info !== null
              ? (info as Record<string, string>)['IPv4 Layer'] || ''
              : ''
            return <InfoRow key={iface} label={iface.slice(0, 20)} value={ipv4} />
          })}
        </Section>
      )}

      {g['WindowsSecurityCenter'] && (
        <Section title="Безопасность">
          {Object.entries(g['WindowsSecurityCenter']).map(([k, v]) => (
            <InfoRow key={k} label={k} value={String(v)} />
          ))}
        </Section>
      )}
    </>
  )
}

const FIELD_LABELS: Record<string, string> = {
  source_type: 'Тип',
  mc_node_name: 'MC устройство',
  manual_label: 'Имя',
  manual_type: 'Тип устройства',
  manual_ip: 'IP',
  manual_mac: 'MAC',
  manual_desc: 'Описание',
  label: 'Метка',
  description: 'Заметки',
  port_type: 'Тип порта',
}

interface HistoryEntry {
  id: number
  field: string
  old_value: string | null
  new_value: string | null
  changed_at: string | null
}

function PortHistoryPanel({ portId }: { portId: number }) {
  const { data, isLoading, isError } = useQuery<HistoryEntry[]>({
    queryKey: ['port-history', portId],
    queryFn: () => api.get(`/ports/${portId}/history`).then(r => r.data),
    staleTime: 10_000,
  })

  if (isLoading) return <div className="text-gray-500 text-xs py-2">Загрузка истории…</div>
  if (isError)   return <div className="text-red-400 text-xs py-2">Ошибка загрузки истории</div>
  if (!data || data.length === 0)
    return <div className="text-gray-500 text-xs py-2 text-center">Изменений ещё не было</div>

  return (
    <div className="mt-1 space-y-1">
      {data.map(h => {
        const label = FIELD_LABELS[h.field] || h.field
        const when  = h.changed_at
          ? new Date(h.changed_at).toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })
          : '?'
        return (
          <div key={h.id} className="text-xs border-b border-gray-800 pb-1">
            <div className="flex justify-between text-gray-500">
              <span className="font-medium text-gray-400">{label}</span>
              <span>{when}</span>
            </div>
            <div className="text-gray-500 line-through truncate">{h.old_value || '—'}</div>
            <div className="text-gray-200 truncate">{h.new_value || '—'}</div>
          </div>
        )
      })}
    </div>
  )
}


export const SidePanel: React.FC<Props> = ({ port, device, onClose, editMode, onEdit }) => {
  const [showHistory, setShowHistory] = useState(false)
  const isMC     = port.source_type === 'mc' && port.mc_node_id
  const isManual = port.source_type === 'manual'
  const isCustom = port.source_type === 'custom'

  const displayName =
    port.label ||
    port.mc_node_name ||
    port.manual_label ||
    `Порт ${port.port_number}`

  const statusColor = isMC
    ? (port.mc_node_online ? 'text-green-400' : 'text-red-400')
    : 'text-blue-400'

  const statusText = isMC
    ? (port.mc_node_online ? '● Online' : '○ Offline')
    : (port.source_type === 'free' ? '— Свободен' : '◉ Устройство')

  return (
    <div className="flex flex-col h-full bg-gray-900 border-l border-gray-700">
      {/* Header */}
      <div className="flex items-start justify-between px-4 py-3 bg-gray-800 border-b border-gray-700">
        <div>
          <div className="font-semibold text-white text-sm">{displayName}</div>
          <div className={`text-xs mt-0.5 ${statusColor}`}>{statusText}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {device.name} · Порт {port.port_number}
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-white text-lg leading-none ml-2">×</button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-2 text-sm">

        {port.source_type === 'free' && (
          <div className="text-gray-500 text-xs py-4 text-center">
            Порт свободен
            {editMode && (
              <div className="mt-2">
                <button
                  onClick={onEdit}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
                >
                  + Назначить устройство
                </button>
              </div>
            )}
          </div>
        )}

        {isMC && (
          <>
            {port.description && (
              <Section title="Заметка">
                <InfoRow label="" value={port.description} />
              </Section>
            )}
            {port.mc_node_id && <MCDetails nodeId={port.mc_node_id} />}
            {port.mc_node_id && (
              <a
                href={`${import.meta.env.VITE_MC_URL ?? ''}/?node=${port.mc_node_id}`}
                target="_blank"
                rel="noreferrer"
                className="inline-block mt-2 px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs rounded"
              >
                ↗ Открыть в MeshCentral
              </a>
            )}
          </>
        )}

        {(isManual || isCustom) && (
          <Section title="Устройство">
            <InfoRow label="Имя"        value={port.manual_label || displayName} />
            <InfoRow label="Тип"        value={port.manual_type || ''} />
            <InfoRow label="IP"         value={port.manual_ip || ''} />
            <InfoRow label="MAC"        value={port.manual_mac || ''} />
            <InfoRow label="Описание"   value={port.manual_desc || port.description || ''} />
          </Section>
        )}

        {port.description && port.source_type !== 'manual' && (
          <Section title="Заметки">
            <p className="text-gray-300 text-xs">{port.description}</p>
          </Section>
        )}

        {/* Port change history */}
        {port.source_type !== 'free' && (
          <div className="mt-3">
            <button
              onClick={() => setShowHistory(v => !v)}
              className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
            >
              {showHistory ? '▲' : '▼'} История изменений
            </button>
            {showHistory && (
              <div className="mt-2">
                <PortHistoryPanel portId={port.id} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer actions */}
      {editMode && port.source_type !== 'free' && (
        <div className="px-4 py-3 border-t border-gray-700 flex gap-2">
          <button
            onClick={onEdit}
            className="flex-1 px-3 py-1.5 bg-yellow-600 hover:bg-yellow-700 text-white text-xs rounded"
          >
            ✏ Изменить
          </button>
        </div>
      )}
    </div>
  )
}
