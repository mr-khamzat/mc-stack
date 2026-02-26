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

// ── Equipment templates ───────────────────────────────────────────────────────
interface Template {
  label:       string
  brand:       string
  model:       string
  device_type: DeviceTypeKey
  port_count:  number
  unit_size:   number
  port_type:   'rj45' | 'sfp' | 'uplink'
}

const TEMPLATES: Template[] = [
  // ── TP-Link ──────────────────────────────────────────────────────────────
  { label: 'TP-Link TL-SG1024DE',    brand: 'TP-Link',   model: 'TL-SG1024DE',      device_type: 'switch',      port_count: 24, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-SG1016DE',    brand: 'TP-Link',   model: 'TL-SG1016DE',      device_type: 'switch',      port_count: 16, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-SG108E',      brand: 'TP-Link',   model: 'TL-SG108E',        device_type: 'switch',      port_count:  8, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-SG3428',      brand: 'TP-Link',   model: 'TL-SG3428',        device_type: 'switch',      port_count: 28, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-SG1210P PoE', brand: 'TP-Link',   model: 'TL-SG1210P',       device_type: 'poe_switch',  port_count: 10, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-SG1218P PoE', brand: 'TP-Link',   model: 'TL-SG1218P',       device_type: 'poe_switch',  port_count: 18, unit_size: 1, port_type: 'rj45' },
  { label: 'TP-Link TL-R480T+',      brand: 'TP-Link',   model: 'TL-R480T+',        device_type: 'router',      port_count:  5, unit_size: 1, port_type: 'rj45' },
  // ── Keenetic ─────────────────────────────────────────────────────────────
  { label: 'Keenetic Ultra',          brand: 'Keenetic',  model: 'Ultra (KN-1811)',  device_type: 'router',      port_count:  4, unit_size: 1, port_type: 'rj45' },
  { label: 'Keenetic Giga',           brand: 'Keenetic',  model: 'Giga (KN-1010)',   device_type: 'router',      port_count:  4, unit_size: 1, port_type: 'rj45' },
  { label: 'Keenetic Hero 4G+',       brand: 'Keenetic',  model: 'Hero 4G+ (KN-2311)', device_type: 'router',   port_count:  4, unit_size: 1, port_type: 'rj45' },
  { label: 'Keenetic Omni',           brand: 'Keenetic',  model: 'Omni (KN-1410)',   device_type: 'router',      port_count:  4, unit_size: 1, port_type: 'rj45' },
  // ── SNR ──────────────────────────────────────────────────────────────────
  { label: 'SNR-S2985G-8T',           brand: 'SNR',       model: 'SNR-S2985G-8T',    device_type: 'switch',      port_count:  8, unit_size: 1, port_type: 'rj45' },
  { label: 'SNR-S2985G-24T',          brand: 'SNR',       model: 'SNR-S2985G-24T',   device_type: 'switch',      port_count: 24, unit_size: 1, port_type: 'rj45' },
  { label: 'SNR-S2985G-48T',          brand: 'SNR',       model: 'SNR-S2985G-48T',   device_type: 'switch',      port_count: 48, unit_size: 1, port_type: 'rj45' },
  { label: 'SNR-S2985G-8T-POE',       brand: 'SNR',       model: 'SNR-S2985G-8T-POE',device_type: 'poe_switch',  port_count:  8, unit_size: 1, port_type: 'rj45' },
  { label: 'SNR-S2985G-24T-POE',      brand: 'SNR',       model: 'SNR-S2985G-24T-POE',device_type:'poe_switch',  port_count: 24, unit_size: 1, port_type: 'rj45' },
  // ── Cisco ─────────────────────────────────────────────────────────────────
  { label: 'Cisco Catalyst 2960-24T', brand: 'Cisco',     model: 'Catalyst 2960-24T',device_type: 'switch',      port_count: 24, unit_size: 1, port_type: 'rj45' },
  { label: 'Cisco Catalyst 2960-48T', brand: 'Cisco',     model: 'Catalyst 2960-48T',device_type: 'switch',      port_count: 48, unit_size: 1, port_type: 'rj45' },
  { label: 'Cisco SG350-28',          brand: 'Cisco',     model: 'SG350-28',         device_type: 'switch',      port_count: 28, unit_size: 1, port_type: 'rj45' },
  { label: 'Cisco SG110-16HP PoE',    brand: 'Cisco',     model: 'SG110-16HP',       device_type: 'poe_switch',  port_count: 16, unit_size: 1, port_type: 'rj45' },
  // ── MikroTik ─────────────────────────────────────────────────────────────
  { label: 'MikroTik hEX S',          brand: 'MikroTik',  model: 'hEX S (RB760iGS)', device_type: 'router',      port_count:  5, unit_size: 1, port_type: 'rj45' },
  { label: 'MikroTik CRS326',         brand: 'MikroTik',  model: 'CRS326-24G-2S+',   device_type: 'switch',      port_count: 26, unit_size: 1, port_type: 'rj45' },
  { label: 'MikroTik CSS326',         brand: 'MikroTik',  model: 'CSS326-24G-2S+',   device_type: 'switch',      port_count: 26, unit_size: 1, port_type: 'rj45' },
  { label: 'MikroTik RB4011',         brand: 'MikroTik',  model: 'RB4011iGS+RM',     device_type: 'router',      port_count: 10, unit_size: 1, port_type: 'rj45' },
  // ── D-Link ───────────────────────────────────────────────────────────────
  { label: 'D-Link DGS-1024D',        brand: 'D-Link',    model: 'DGS-1024D',        device_type: 'switch',      port_count: 24, unit_size: 1, port_type: 'rj45' },
  { label: 'D-Link DGS-1008P PoE',    brand: 'D-Link',    model: 'DGS-1008P',        device_type: 'poe_switch',  port_count:  8, unit_size: 1, port_type: 'rj45' },
  // ── Патч-панели ──────────────────────────────────────────────────────────
  { label: 'Hyperline PP 24p',         brand: 'Hyperline', model: 'PP-19-24-8P8C-C5E',device_type: 'patch_panel', port_count: 24, unit_size: 1, port_type: 'rj45' },
  { label: 'Hyperline PP 48p',         brand: 'Hyperline', model: 'PP-19-48-8P8C-C5E',device_type: 'patch_panel', port_count: 48, unit_size: 2, port_type: 'rj45' },
  { label: 'Panduit 24p',              brand: 'Panduit',   model: 'DP24E88TGY',       device_type: 'patch_panel', port_count: 24, unit_size: 1, port_type: 'rj45' },
  // ── Серверы ──────────────────────────────────────────────────────────────
  { label: 'Dell PowerEdge R720',      brand: 'Dell',      model: 'PowerEdge R720',   device_type: 'server',      port_count:  4, unit_size: 2, port_type: 'rj45' },
  { label: 'Dell PowerEdge R750',      brand: 'Dell',      model: 'PowerEdge R750',   device_type: 'server',      port_count:  4, unit_size: 2, port_type: 'rj45' },
  { label: 'HPE ProLiant DL380',       brand: 'HPE',       model: 'ProLiant DL380',   device_type: 'server',      port_count:  4, unit_size: 2, port_type: 'rj45' },
  { label: 'Supermicro 1U',            brand: 'Supermicro',model: '1U Server',        device_type: 'server',      port_count:  2, unit_size: 1, port_type: 'rj45' },
]

// Group templates by brand for the dropdown
const TEMPLATE_BRANDS = Array.from(new Set(TEMPLATES.map(t => t.brand)))

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

interface FormState {
  name:        string
  device_type: DeviceTypeKey
  rack_unit:   number
  unit_size:   number
  port_count:  number
  port_type:   'rj45' | 'sfp' | 'uplink'
  color:       string
  notes:       string
  brand:       string
  model:       string
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
  brand:       '',
  model:       '',
})

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
  const [editId,         setEditId]         = useState<number | null>(null)
  const [showForm,       setShowForm]       = useState(false)
  const [form,           setForm]           = useState<FormState>(emptyForm())
  const [confirmDelete,  setConfirmDelete]  = useState<RackDevice | null>(null)
  const [confirmClear,   setConfirmClear]   = useState(false)
  const [selectedBrand,  setSelectedBrand]  = useState('')

  const { data: rack = [] } = useQuery<RackDevice[]>({
    queryKey: ['rack'],
    queryFn: () => api.get('/rack').then(r => r.data),
  })

  const addDevice = useMutation({
    mutationFn: (body: FormState) => api.post('/rack/devices', {
      ...body,
      notes: body.notes || null,
      brand: body.brand || null,
      model: body.model || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setShowForm(false); setForm(emptyForm()) },
  })

  const updateDevice = useMutation({
    mutationFn: ({ id, body }: { id: number; body: FormState }) =>
      api.put(`/rack/devices/${id}`, {
        ...body,
        notes: body.notes || null,
        brand: body.brand || null,
        model: body.model || null,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setShowForm(false); setEditId(null) },
  })

  const deleteDevice = useMutation({
    mutationFn: (id: number) => api.delete(`/rack/devices/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rack'] }); setConfirmDelete(null) },
  })

  const clearAll = useMutation({
    mutationFn: () => api.delete('/rack/devices'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rack'] })
      qc.invalidateQueries({ queryKey: ['callouts'] })
      setConfirmClear(false)
      setShowForm(false)
    },
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
      brand:       d.brand || '',
      model:       d.model || '',
    })
    setShowForm(true)
  }

  const applyTemplate = (tpl: Template) => {
    setForm(f => ({
      ...f,
      device_type: tpl.device_type,
      port_count:  tpl.port_count,
      unit_size:   tpl.unit_size,
      port_type:   tpl.port_type,
      brand:       tpl.brand,
      model:       tpl.model,
      // Auto-fill name if empty
      name: f.name || tpl.model,
    }))
    setSelectedBrand('')
  }

  const handleTypeChange = (newType: DeviceTypeKey) => {
    if (editId !== null) {
      setForm(f => ({ ...f, device_type: newType }))
      return
    }
    const def = TYPE_DEFAULTS[newType]
    setForm(f => ({ ...f, device_type: newType, port_count: def.port_count, unit_size: def.unit_size, port_type: def.port_type }))
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
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-[740px] max-h-[88vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <div>
            <div className="font-semibold text-white text-sm">Управление стойкой</div>
            <div className="text-xs text-gray-400 mt-0.5">{rack.length} устройств · добавляйте, редактируйте, удаляйте</div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setConfirmClear(true)}
              className="text-xs text-red-500 hover:text-red-300 px-2 py-1 rounded border border-red-900 hover:border-red-700"
              title="Удалить все устройства из стойки"
            >
              🗑 Очистить стойку
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">×</button>
          </div>
        </div>

        <div className="flex flex-1 overflow-hidden">

          {/* Left: device list */}
          <div className="flex-1 overflow-y-auto border-r border-gray-800">
            {sorted.map(d => (
              <div key={d.id}
                className={`flex items-center gap-3 px-4 py-2.5 border-b border-gray-800 hover:bg-gray-800 ${editId === d.id ? 'bg-gray-800' : ''}`}>
                <span className="text-gray-500 text-xs w-8 shrink-0 font-mono">{d.rack_unit}U</span>
                <span className="px-1.5 py-0.5 bg-gray-700 text-gray-300 text-xs rounded font-mono shrink-0">
                  {d.device_type.toUpperCase().slice(0, 3)}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-white text-xs font-medium truncate">{d.name}</div>
                  <div className="text-gray-500 text-xs">
                    {d.brand
                      ? <span className="text-gray-400">{d.brand} {d.model}</span>
                      : DEVICE_TYPE_FULL[d.device_type as DeviceTypeKey] || d.device_type
                    }
                    {' · '}{d.port_count} п.
                    {d.notes && <span className="text-gray-600 ml-1 italic">· {d.notes.slice(0, 25)}{d.notes.length > 25 ? '…' : ''}</span>}
                  </div>
                </div>
                <button onClick={() => openEdit(d)}
                  className="text-blue-400 hover:text-blue-300 text-xs px-2 py-1 rounded hover:bg-blue-900/30">✏</button>
                <button onClick={() => setConfirmDelete(d)}
                  className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded hover:bg-red-900/30">×</button>
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
            <div className="w-80 shrink-0 p-4 overflow-y-auto">
              <div className="text-xs font-semibold text-gray-300 mb-3">
                {editId !== null ? 'Редактировать устройство' : 'Новое устройство'}
              </div>

              {/* ── Template picker ─────────────────────────────────── */}
              {editId === null && (
                <div className="mb-3">
                  <label className="text-gray-400 text-xs block mb-1">Шаблон оборудования</label>
                  <div className="flex gap-1.5 flex-wrap mb-1.5">
                    {TEMPLATE_BRANDS.map(brand => (
                      <button
                        key={brand}
                        onClick={() => setSelectedBrand(b => b === brand ? '' : brand)}
                        className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                          selectedBrand === brand
                            ? 'bg-blue-800 border-blue-500 text-blue-200'
                            : 'bg-gray-800 border-gray-600 text-gray-400 hover:text-white'
                        }`}
                      >
                        {brand}
                      </button>
                    ))}
                  </div>
                  {selectedBrand && (
                    <select
                      onChange={e => {
                        const tpl = TEMPLATES.find(t => t.label === e.target.value)
                        if (tpl) applyTemplate(tpl)
                      }}
                      defaultValue=""
                      className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-blue-600 mb-1 focus:outline-none"
                    >
                      <option value="" disabled>Выбери модель…</option>
                      {TEMPLATES.filter(t => t.brand === selectedBrand).map(t => (
                        <option key={t.label} value={t.label}>{t.model}</option>
                      ))}
                    </select>
                  )}
                  <div className="border-t border-gray-700 my-2" />
                </div>
              )}

              {/* ── Name ────────────────────────────────────────────── */}
              <label className="text-gray-400 text-xs block mb-1">Название *</label>
              <input
                autoFocus
                value={form.name}
                onChange={e => setForm(f => ({...f, name: e.target.value}))}
                onKeyDown={e => e.key === 'Enter' && submit()}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500"
                placeholder="SW-01, Keenetic, Patch Panel 1..."
              />

              {/* ── Brand + Model ────────────────────────────────────── */}
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Бренд</label>
                  <input
                    value={form.brand}
                    onChange={e => setForm(f => ({...f, brand: e.target.value}))}
                    list="brand-list"
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                    placeholder="TP-Link, Cisco…"
                  />
                  <datalist id="brand-list">
                    {TEMPLATE_BRANDS.map(b => <option key={b} value={b} />)}
                  </datalist>
                </div>
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Модель</label>
                  <input
                    value={form.model}
                    onChange={e => setForm(f => ({...f, model: e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                    placeholder="TL-SG1024DE…"
                  />
                </div>
              </div>

              {/* ── Type ─────────────────────────────────────────────── */}
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

              {/* ── Position + size ───────────────────────────────────── */}
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">U-позиция</label>
                  <input type="number" min={1} max={50}
                    value={form.rack_unit}
                    onChange={e => setForm(f => ({...f, rack_unit: +e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Размер (U)</label>
                  <input type="number" min={1} max={10}
                    value={form.unit_size}
                    onChange={e => setForm(f => ({...f, unit_size: +e.target.value}))}
                    className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* ── Ports ────────────────────────────────────────────── */}
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <label className="text-gray-400 text-xs block mb-1">Кол-во портов</label>
                  <input type="number" min={0} max={96}
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

              {/* ── Notes ────────────────────────────────────────────── */}
              <label className="text-gray-400 text-xs block mb-1">
                Заметка <span className="text-gray-600">(видна на устройстве)</span>
              </label>
              <textarea
                value={form.notes}
                onChange={e => setForm(f => ({...f, notes: e.target.value}))}
                rows={2} maxLength={80}
                className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500 resize-none"
                placeholder="Серверная A, 3-й этаж..."
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

      {/* Confirm delete device */}
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
              <button onClick={() => setConfirmDelete(null)}
                className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded">Отмена</button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm clear all */}
      {confirmClear && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black bg-opacity-60">
          <div className="bg-gray-900 border border-red-900 rounded-lg p-5 w-80 shadow-2xl">
            <div className="text-red-400 text-sm font-semibold mb-2">⚠ Очистить стойку?</div>
            <div className="text-gray-400 text-xs mb-4">
              Будут удалены <span className="text-white font-medium">все {rack.length} устройств</span> со всеми портами и аннотациями.
              <div className="mt-2 text-red-400 font-medium">Это действие необратимо!</div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => clearAll.mutate()}
                disabled={clearAll.isPending}
                className="flex-1 py-1.5 bg-red-800 hover:bg-red-700 text-white text-xs rounded font-medium"
              >
                {clearAll.isPending ? 'Удаление…' : '🗑 Да, удалить всё'}
              </button>
              <button onClick={() => setConfirmClear(false)}
                className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded">Отмена</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
