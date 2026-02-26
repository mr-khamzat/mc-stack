import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Port, RackDevice, MCAgent, WifiNeighbor } from '../types'

interface Props {
  port:    Port
  device:  RackDevice
  onClose: () => void
}

type Tab = 'mc' | 'network' | 'manual'

const MANUAL_TYPES = ['switch', 'router', 'ap', 'printer', 'camera', 'server', 'other']

function AgentRow({ agent, onSelect }: { agent: MCAgent; onSelect: (a: MCAgent) => void }) {
  return (
    <button
      onClick={() => onSelect(agent)}
      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800 border-b border-gray-800 text-left transition-colors"
    >
      <span className={`text-xs font-bold ${agent.online ? 'text-green-400' : 'text-gray-500'}`}>
        {agent.online ? '●' : '○'}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-white text-xs font-medium truncate">{agent.name}</div>
        <div className="text-gray-500 text-xs">{agent.ip || ''}</div>
        {agent.os && <div className="text-gray-600 text-xs truncate">{agent.os}</div>}
      </div>
      <span className="text-blue-400 text-xs shrink-0">↵</span>
    </button>
  )
}

export const EditModal: React.FC<Props> = ({ port, device, onClose }) => {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('mc')
  const [search, setSearch] = useState('')
  const [manualLabel, setManualLabel] = useState(port.manual_label || '')
  const [manualType,  setManualType]  = useState(port.manual_type || 'other')
  const [manualIp,    setManualIp]    = useState(port.manual_ip || '')
  const [manualMac,   setManualMac]   = useState(port.manual_mac || '')
  const [manualDesc,  setManualDesc]  = useState(port.manual_desc || port.description || '')

  // Fetch MC agents
  const { data: agents = [], isLoading: loadingAgents } = useQuery<MCAgent[]>({
    queryKey: ['agents'],
    queryFn: () => api.get('/mc/agents').then(r => r.data),
    staleTime: 30_000,
  })

  // Fetch wifi neighbors
  const { data: neighbors = [], isLoading: loadingNeighbors } = useQuery<WifiNeighbor[]>({
    queryKey: ['wifi-neighbors'],
    queryFn: () => api.get('/mc/wifi-neighbors').then(r => r.data),
    staleTime: 60_000,
    enabled: tab === 'network',
  })

  const patchPort = useMutation({
    mutationFn: (body: object) => api.patch(`/ports/${port.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rack'] })
      onClose()
    },
  })

  const freePort = useMutation({
    mutationFn: () => api.post(`/ports/${port.id}/free`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rack'] })
      onClose()
    },
  })

  const assignMC = (agent: MCAgent) => {
    patchPort.mutate({
      source_type:    'mc',
      mc_node_id:     agent.id,
      mc_node_name:   agent.name,
      mc_node_online: agent.online ? 1 : 0,
      label:          agent.name,
    })
  }

  const assignNeighbor = (n: WifiNeighbor) => {
    patchPort.mutate({
      source_type:  'manual',
      manual_label: n.name || n.ip,
      manual_type:  n.type === 'WiFi' ? 'ap' : 'other',
      manual_ip:    n.ip,
      manual_mac:   n.mac,
      manual_desc:  `${n.location} · ${n.iface}`,
      label:        n.name || n.ip,
    })
  }

  const assignManual = () => {
    if (!manualLabel.trim()) return
    patchPort.mutate({
      source_type:  'manual',
      manual_label: manualLabel,
      manual_type:  manualType,
      manual_ip:    manualIp,
      manual_mac:   manualMac,
      manual_desc:  manualDesc,
      label:        manualLabel,
    })
  }

  const filteredAgents = agents.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.group.toLowerCase().includes(search.toLowerCase()) ||
    a.ip.includes(search)
  )

  // Group agents by office when not searching
  const groupedAgents: Record<string, MCAgent[]> = {}
  if (!search) {
    filteredAgents.forEach(a => {
      const g = a.group || 'Без группы'
      if (!groupedAgents[g]) groupedAgents[g] = []
      groupedAgents[g].push(a)
    })
  }
  const filteredNeighbors = neighbors.filter(n =>
    (n.name || '').toLowerCase().includes(search.toLowerCase()) ||
    n.ip.includes(search) ||
    n.mac.toLowerCase().includes(search.toLowerCase()) ||
    n.location.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70"
         onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-[500px] max-h-[80vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <div>
            <div className="font-semibold text-white text-sm">
              Порт {port.port_number} · {device.name}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">Назначить устройство</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-700">
          {([
            { id: 'mc',      label: '🖥 MC Агенты'   },
            { id: 'network', label: '🔌 Сеть'         },
            { id: 'manual',  label: '✏ Вручную'       },
          ] as { id: Tab; label: string }[]).map(t => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setSearch('') }}
              className={`flex-1 py-2 text-xs font-medium transition-colors
                ${tab === t.id
                  ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-800'
                  : 'text-gray-400 hover:text-gray-200'}`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Search bar (mc + network) */}
        {tab !== 'manual' && (
          <div className="px-3 py-2 border-b border-gray-800">
            <input
              autoFocus
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={tab === 'mc' ? 'Поиск агента…' : 'Поиск по IP / MAC / имени…'}
              className="w-full bg-gray-800 text-white text-xs px-3 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
            />
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto">

          {/* ── MC Agents ── */}
          {tab === 'mc' && (
            <div>
              {loadingAgents && (
                <div className="text-center text-gray-500 text-xs py-6">Загрузка агентов…</div>
              )}
              {!loadingAgents && filteredAgents.length === 0 && (
                <div className="text-center text-gray-500 text-xs py-6">Агенты не найдены</div>
              )}
              {/* Search mode — flat list */}
              {search && filteredAgents.map(a => (
                <AgentRow key={a.id} agent={a} onSelect={assignMC} />
              ))}
              {/* Browse mode — grouped by office */}
              {!search && Object.entries(groupedAgents).sort(([a],[b]) => a.localeCompare(b)).map(([group, list]) => (
                <div key={group}>
                  <div className="px-4 py-1.5 bg-gray-800 border-b border-gray-700 sticky top-0">
                    <span className="text-xs font-semibold text-gray-300">🏢 {group}</span>
                    <span className="text-xs text-gray-500 ml-2">
                      {list.filter(a => a.online).length} online / {list.length}
                    </span>
                  </div>
                  {list.map(a => (
                    <AgentRow key={a.id} agent={a} onSelect={assignMC} />
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* ── Network neighbors (from WiFi probe) ── */}
          {tab === 'network' && (
            <div>
              {loadingNeighbors && (
                <div className="text-center text-gray-500 text-xs py-6">Загрузка соседей сети…</div>
              )}
              {!loadingNeighbors && filteredNeighbors.length === 0 && (
                <div className="text-center text-gray-500 text-xs py-6">
                  <p>Устройства не найдены</p>
                  <p className="text-gray-600 mt-1">Запустите WiFi-зонд в боте для обновления данных</p>
                </div>
              )}
              {filteredNeighbors.map((n, i) => (
                <button
                  key={i}
                  onClick={() => assignNeighbor(n)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800 border-b border-gray-800 text-left transition-colors"
                >
                  <span className="text-xs">{n.type === 'WiFi' ? '📶' : '🔌'}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-white text-xs font-medium truncate">
                      {n.name || n.ip || n.mac}
                    </div>
                    <div className="text-gray-500 text-xs">
                      {n.ip && `IP: ${n.ip}`}
                      {n.mac && ` · MAC: ${n.mac}`}
                    </div>
                    <div className="text-gray-600 text-xs">{n.location}{n.iface ? ` · ${n.iface}` : ''}</div>
                  </div>
                  <span className="text-blue-400 text-xs shrink-0">↵</span>
                </button>
              ))}
            </div>
          )}

          {/* ── Manual entry ── */}
          {tab === 'manual' && (
            <div className="px-4 py-3 space-y-3">
              <div>
                <label className="text-gray-400 text-xs block mb-1">Название устройства *</label>
                <input
                  autoFocus
                  value={manualLabel}
                  onChange={e => setManualLabel(e.target.value)}
                  placeholder="Cisco SW-01, TP-Link Router, Камера 3..."
                  className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-gray-400 text-xs block mb-1">Тип устройства</label>
                <select
                  value={manualType}
                  onChange={e => setManualType(e.target.value)}
                  className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                >
                  {MANUAL_TYPES.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">IP адрес</label>
                  <input
                    value={manualIp}
                    onChange={e => setManualIp(e.target.value)}
                    placeholder="192.168.1.1"
                    className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-gray-400 text-xs block mb-1">MAC адрес</label>
                  <input
                    value={manualMac}
                    onChange={e => setManualMac(e.target.value)}
                    placeholder="AA:BB:CC:DD:EE:FF"
                    className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
              <div>
                <label className="text-gray-400 text-xs block mb-1">Описание / заметки</label>
                <textarea
                  value={manualDesc}
                  onChange={e => setManualDesc(e.target.value)}
                  rows={2}
                  placeholder="Этаж 2, кабинет 204..."
                  className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded border border-gray-600 focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
              <button
                onClick={assignManual}
                disabled={!manualLabel.trim() || patchPort.isPending}
                className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs rounded font-medium"
              >
                {patchPort.isPending ? 'Сохранение…' : '✓ Сохранить'}
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-700 flex justify-between items-center">
          {port.source_type !== 'free' && (
            <button
              onClick={() => freePort.mutate()}
              disabled={freePort.isPending}
              className="text-red-400 hover:text-red-300 text-xs"
            >
              🗑 Освободить порт
            </button>
          )}
          <div />
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 text-xs">
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}
