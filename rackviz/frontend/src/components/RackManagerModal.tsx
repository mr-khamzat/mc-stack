import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RackDevice } from '../types'

interface Props {
  onClose: () => void
}

type DeviceTypeKey = 'patch_panel' | 'switch' | 'hub' | 'router' | 'server' | 'poe_switch' | 'isp' | 'auth_router' | 'other'

const DEVICE_TYPE_FULL: Record<DeviceTypeKey, string> = {
  patch_panel: 'Патч-панель',
  switch:      'Коммутатор',
  hub:         'Хаб',
  router:      'Роутер',
  server:      'Сервер',
  poe_switch:  'PoE Switch',
  isp:         'ISP Switch',
  auth_router: 'Auth Router',
  other:       'Другое',
}

// Smart defaults per device type
const TYPE_DEFAULTS: Record<DeviceTypeKey, { port_count: number; unit_size: number; port_type: 'rj45' | 'sfp' | 'uplink' }> = {
  patch_panel: { port_count: 24, unit_size: 1, port_type: 'rj45' },
  switch:      { port_count: 24, unit_size: 1, port_type: 'rj45' },
  hub:         { port_count: 8,  unit_size: 1, port_type: 'rj45' },
  router:      { port_count: 4,  unit_size: 1, port_type: 'rj45' },
  server:      { port_count: 2,  unit_size: 2, port_type: 'rj45' },
  poe_switch:  { port_count: 24, unit_size: 1, port_type: 'rj45' },
  isp:         { port_count: 24, unit_size: 1, port_type: 'rj45' },
  auth_router: { port_count: 4,  unit_size: 1, port_type: 'rj45' },
  other:       { port_count: 8,  unit_size: 1, port_type: 'rj45' },
}

const DEVICE_COLORS = [
  { label: 'Серый (по умолч.)', value: '#2a2a3a' },
  { label: 'Синий (патч)',       value: '#1e2a3a' },
  { label: 'Зелёный (коммутатор)', value: '#1a2e1a' },
  { label: 'Коричневый (сервер)', value: '#2e1a0e' },
  { label: 'Тёмно-серый',        value: '#3a3a4a' },
]

interface FormState {
  name:        string
  device_type: DeviceTypeKey
  rack_unit:   number
  unit_size:   number
  port_count:  number
  port_type:   'rj45' | 'sfp' | 'uplink'
  color:       string
  notes:       string
}

const emptyForm = (nextUnit = 1): FormState => ({
  name:        '',
  device_type: 'switch',
  rack_unit:   nextUnit,
  unit_size:   1,
  port_count:  24,
  port_type:   'rj45',
  color:       '#2a2a3a',
  notes:       '',
})

/** Find the next free rack unit after all existing devices */
function nextFreeUnit(rack: RackDevice[]): number {
  if (!rack.length) return 1
  const occupied = new Set<number>()
  for (const d of rack) {
    for (let u = d.rack_unit; u < d.rack_unit + d.unit_size; u++) occupied.add(u)
  }
  let u = 1
  while (occupied.has(u)) u++
  return u
}

export const RackManagerModal: React.FC<Props> = ({ onClose }) => {
  const qc = useQueryClient()
  const [editId, setEditId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [confirmDelete, setConfirmDelete] = useState<RackDevice | null>(null)

  const { data: rack = [] } = useQuery<RackDevice[]>({
    queryKey: ['rack'],
    queryFn: () => api.get('/rack').then(r => r.data),
  })

  const addDevice = useMutation({
    mutationFn: (body: FormState) => api.post('/rack/devices', { ...body, notes: body.notes || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setShowForm(false); setForm(emptyForm()) },
  })

  const updateDevice = useMutation({
    mutationFn: ({ id, body }: { id: number; body: FormState }) =>
      api.put(`/rack/devices/${id}`, { ...body, notes: body.notes || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setShowForm(false); setEditId(null) },
  })

  const deleteDevice = useMutation({
    mutationFn: (id: number) => api.delete(`/rack/devices/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setConfirmDelete(null) },
  })

  const openAdd = () => {
    setEditId(null)
    setForm(emptyForm(nextFreeUnit(rack)))
    setShowForm(true)
  }

  const openEdit = (d: RackDevice) => {
    setEditId(d.id)
    setForm({
      name:        d.name,
      device_type: d.device_type as DeviceTypeKey,
      rack_unit:   d.rack_unit,
      unit_size:   d.unit_size,
      port_count:  d.port_count,
      port_type:   d.port_type,
      color:       d.color,
      notes:       d.notes || '',
    })
    setShowForm(true)
  }

  // When device type changes, apply smart defaults (only for new devices)
  const handleTypeChange = (newType: DeviceTypeKey) => {
    if (editId !== null) {
      setForm(f => ({ ...f, device_type: newType }))
      return
    }
    const def = TYPE_DEFAULTS[newType]
    setForm(f => ({
      ...f,
      device_type: newType,
      port_count:  def.port_count,
      unit_size:   def.unit_size,
      port_type:   def.port_type,
    }))
  }

  const submit = () => {
    if (!form.name.trim()) return
    if (editId !== null) {
      updateDevice.mutate({ id: editId, body: form })
    } else {
      addDevice.mutate(form)
    }
  }

  const sorted = [...rack].sort((a, b) => a.rack_unit - b.rack_unit)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70"
         onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-[680px] max-h-[85vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <div>
            <div className="font-semibold text-white text-sm">Управление стойкой</div>
            <div className="text-xs text-gray-400 mt-0.5">{rack.length} устройств · добавляйте, редактируйте, удаляйте</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="flex flex-1 overflow-hidden">

          {/* Left: device list */}
          <div className="flex-1 overflow-y-auto border-r border-gray-800">
            {sorted.map(d => (
              <div key={d.id}
                className={`flex items-center gap-3 px-4 py-2.5 border-b border-gray-800 hover:bg-gray-800
                  ${editId === d.id ? 'bg-gray-800' : ''}`}>
                <span className="text-gray-500 text-xs w-8 shrink-0 font-mono">{d.rack_unit}U</span>
                <span className="px-1.5 py-0.5 bg-gray-700 text-gray-300 text-xs rounded font-mono shrink-0">
                  {d.device_type.toUpperCase().slice(0, 3)}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-white text-xs font-medium truncate">{d.name}</div>
                  <div className="text-gray-500 text-xs">
                    {DEVICE_TYPE_FULL[d.device_type as DeviceTypeKey] || d.device_type} · {d.port_count} п.
                    {d.notes && <span className="text-gray-600 ml-1 italic">· {d.notes.slice(0, 30)}{d.notes.length > 30 ? '…' : ''}</span>}
                  </div>
                </div>
                <button
                  onClick={() => openEdit(d)}
                  className="text-blue-400 hover:text-blue-300 text-xs px-2 py-1 rounded hover:bg-blue-900/30"
                >✏</button>
                <button
                  onClick={() => setConfirmDelete(d)}
                  className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded hover:bg-red-900/30"
                >×</button>
              </div>
            ))}
            <div className="px-4 py-3">
              <button
                onClick={openAdd}
                className="w-full py-2 bg-green-700 hover:bg-green-600 text-white text-xs rounded font-medium"
              >
                + Добавить устройство
              </button>
            </div>
          </div>

          {/* Right: add/edit form */}
          {showForm && (
            <div className="w-72 shrink-0 p-4 overflow-y-auto">
              <div className="text-xs font-semibold text-gray-300 mb-3">
                {editId !== null ? 'Редактировать устройство' : 'Новое устройство'}
              </div>

              <label className="text-gray-400 text-xs block mb-1">Название *</label>
              <input
                autoFocus
                value={form.name}
                onChange={e => setForm(f => ({...f, name: e.target.value}))}
                onKeyDown={e => e.key === 'Enter' && submit()}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500"
                placeholder="SW-01, Patch Panel 1..."
              />

              <label className="text-gray-400 text-xs block mb-1">Тип</label>
              <select
                value={form.device_type}
                onChange={e => handleTypeChange(e.target.value as DeviceTypeKey)}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500"
              >
                {Object.entries(DEVICE_TYPE_FULL).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>

              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">U-позиция</label>
                  <input
                    type="number" min={1} max={50}
                    value={form.rack_unit}
                    onChange={e => setForm(f => ({...f, rack_unit: +e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Размер (U)</label>
                  <input
                    type="number" min={1} max={10}
                    value={form.unit_size}
                    onChange={e => setForm(f => ({...f, unit_size: +e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Кол-во портов</label>
                  <input
                    type="number" min={0} max={96}
                    value={form.port_count}
                    onChange={e => setForm(f => ({...f, port_count: +e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Тип порта</label>
                  <select
                    value={form.port_type}
                    onChange={e => setForm(f => ({...f, port_type: e.target.value as 'rj45'|'sfp'|'uplink'}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  >
                    <option value="rj45">RJ45</option>
                    <option value="sfp">SFP</option>
                    <option value="uplink">Uplink</option>
                  </select>
                </div>
              </div>

              <label className="text-gray-400 text-xs block mb-1">Цвет фона</label>
              <select
                value={form.color}
                onChange={e => setForm(f => ({...f, color: e.target.value}))}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-1 focus:outline-none focus:border-blue-500"
              >
                {DEVICE_COLORS.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <div className="w-full h-4 rounded mb-3" style={{ background: form.color }} />

              <label className="text-gray-400 text-xs block mb-1">
                Заметка <span className="text-gray-600">(видна прямо на устройстве)</span>
              </label>
              <textarea
                value={form.notes}
                onChange={e => setForm(f => ({...f, notes: e.target.value}))}
                rows={2}
                maxLength={80}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500 resize-none"
                placeholder="Серверная A, 3-й этаж, замена в 2025..."
              />

              <div className="flex gap-2">
                <button
                  onClick={submit}
                  disabled={!form.name.trim() || addDevice.isPending || updateDevice.isPending}
                  className="flex-1 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs rounded font-medium"
                >
                  {addDevice.isPending || updateDevice.isPending ? 'Сохранение…' : '✓ Сохранить'}
                </button>
                <button
                  onClick={() => { setShowForm(false); setEditId(null) }}
                  className="px-3 py-1.5 text-gray-400 hover:text-white text-xs rounded border border-gray-700"
                >
                  Отмена
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirm delete dialog */}
      {confirmDelete && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black bg-opacity-60">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 shadow-2xl">
            <div className="text-white text-sm font-semibold mb-2">Удалить устройство?</div>
            <div className="text-gray-400 text-xs mb-4">
              <span className="text-white">{confirmDelete.name}</span> · U{confirmDelete.rack_unit} · {confirmDelete.port_count} портов
              <div className="mt-1 text-yellow-400">Все назначения портов будут удалены!</div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => deleteDevice.mutate(confirmDelete.id)}
                disabled={deleteDevice.isPending}
                className="flex-1 py-1.5 bg-red-700 hover:bg-red-600 text-white text-xs rounded"
              >
                {deleteDevice.isPending ? 'Удаление…' : 'Удалить'}
              </button>
              <button
                onClick={() => setConfirmDelete(null)}
                className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
