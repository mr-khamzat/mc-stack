import React, { useState, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api/client'
import { useRackStore } from './store/useRackStore'
import { RackView } from './components/RackView'
import { SidePanel } from './components/SidePanel'
import { EditModal } from './components/EditModal'
import { Toolbar } from './components/Toolbar'
import { RackManagerModal } from './components/RackManagerModal'
import { HelpModal } from './components/HelpModal'
import { StatsPanel } from './components/StatsPanel'
import { CalloutModal } from './components/CalloutModal'
import type { Port, RackDevice, Callout } from './types'

export default function App() {
  const {
    mode, isAdmin, selectedPort, selectedDevice, sidePanelOpen,
    selectPort, closeSidePanel, setAdmin,
  } = useRackStore()

  const [editTarget, setEditTarget] = useState<{ port: Port; device: RackDevice } | null>(null)
  const [showRackManager, setShowRackManager] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [calloutMode, setCalloutMode] = useState(false)
  const [calloutTarget, setCalloutTarget] = useState<{ deviceId: number; existing?: Callout } | null>(null)

  const queryClient = useQueryClient()

  // Restore admin session from localStorage token on page load
  useEffect(() => {
    const token = localStorage.getItem('rack_token')
    if (token && !isAdmin) {
      api.get('/auth/me').then(() => {
        setAdmin(true, token)
      }).catch(() => {
        localStorage.removeItem('rack_token')
      })
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const { data: rack = [], isLoading, isError } = useQuery<RackDevice[]>({
    queryKey: ['rack'],
    queryFn:  () => api.get('/rack').then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: callouts = [] } = useQuery<Callout[]>({
    queryKey: ['callouts'],
    queryFn:  () => api.get('/callouts').then(r => r.data),
    refetchInterval: 60_000,
  })

  // ── Port search ──────────────────────────────────────────────────────────
  const { highlightPortIds, matchCount } = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return { highlightPortIds: undefined, matchCount: 0 }
    const ids = new Set<number>()
    for (const dev of rack) {
      const devMatch = dev.name.toLowerCase().includes(q)
      for (const port of dev.ports) {
        const match =
          devMatch ||
          port.mc_node_name?.toLowerCase().includes(q) ||
          port.manual_label?.toLowerCase().includes(q) ||
          port.manual_ip?.toLowerCase().includes(q) ||
          port.manual_mac?.toLowerCase().includes(q) ||
          port.label?.toLowerCase().includes(q) ||
          String(port.port_number).includes(q)
        if (match && port.source_type !== 'free') ids.add(port.id)
      }
    }
    return { highlightPortIds: ids, matchCount: ids.size }
  }, [searchQuery, rack])

  // ── Port click handling ──────────────────────────────────────────────────
  const handlePortClick = (port: Port, device: RackDevice) => {
    if (mode === 'edit') {
      setEditTarget({ port, device })
    } else {
      if (port.source_type !== 'free') {
        selectPort(port, device)
      }
    }
  }

  // ── Device reorder (DnD list-style, packs tight, no gaps) ───────────────
  const handleReorder = async (orderedIds: number[]) => {
    try {
      await api.post('/rack/devices/reorder', { device_ids: orderedIds })
      queryClient.invalidateQueries({ queryKey: ['rack'] })
    } catch (err) {
      console.error('Reorder failed', err)
    }
  }

  // ── Auto-compact: send current order → backend repacks from U1 ───────────
  const handleCompact = async () => {
    const ids = [...rack].sort((a, b) => a.rack_unit - b.rack_unit).map(d => d.id)
    await handleReorder(ids)
  }

  // ── Callout handlers ─────────────────────────────────────────────────────
  const handleDeviceCalloutClick = (deviceId: number) => {
    const existing = callouts.find(c => c.device_id === deviceId)
    setCalloutTarget({ deviceId, existing })
  }

  const handleCalloutClick = (callout: Callout) => {
    setCalloutTarget({ deviceId: callout.device_id, existing: callout })
  }

  const handleCalloutSave = async (text: string, color: string) => {
    if (!calloutTarget) return
    const { deviceId, existing } = calloutTarget
    try {
      if (existing) {
        await api.patch(`/callouts/${existing.id}`, { text, color })
      } else {
        await api.post('/callouts', { device_id: deviceId, text, color })
      }
      queryClient.invalidateQueries({ queryKey: ['callouts'] })
    } catch (err) {
      console.error('Callout save failed', err)
    }
  }

  const handleCalloutDelete = async () => {
    if (!calloutTarget?.existing) return
    try {
      await api.delete(`/callouts/${calloutTarget.existing.id}`)
      queryClient.invalidateQueries({ queryKey: ['callouts'] })
    } catch (err) {
      console.error('Callout delete failed', err)
    }
  }

  const handleSidePanelEdit = () => {
    if (selectedPort && selectedDevice) {
      setEditTarget({ port: selectedPort, device: selectedDevice })
    }
  }

  const handleDownloadPDF = () => {
    const a = document.createElement('a')
    a.href = '/rack/api/rack/export/pdf'
    a.download = `rack_${new Date().toISOString().slice(0, 10)}.pdf`
    a.click()
  }

  const handleDownloadPNG = () => {
    const svg = document.querySelector<SVGSVGElement>('svg')
    if (!svg) return
    const rect   = svg.getBoundingClientRect()
    const scale  = 2  // retina
    const canvas = document.createElement('canvas')
    canvas.width  = rect.width  * scale
    canvas.height = rect.height * scale
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(scale, scale)
    ctx.fillStyle = '#030712'  // bg-gray-950
    ctx.fillRect(0, 0, rect.width, rect.height)
    const serialized = new XMLSerializer().serializeToString(svg)
    const blob = new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' })
    const url  = URL.createObjectURL(blob)
    const img  = new Image()
    img.onload = () => {
      ctx.drawImage(img, 0, 0)
      URL.revokeObjectURL(url)
      canvas.toBlob(pngBlob => {
        if (!pngBlob) return
        const a  = document.createElement('a')
        a.download = `rack_${new Date().toISOString().slice(0, 10)}.png`
        a.href = URL.createObjectURL(pngBlob)
        a.click()
        setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
      }, 'image/png')
    }
    img.src = url
  }

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100">
      <Toolbar
        onManageRack={() => setShowRackManager(true)}
        onHelp={() => setShowHelp(true)}
        onStats={() => setShowStats(v => !v)}
        onDownloadPNG={handleDownloadPNG}
        onDownloadPDF={handleDownloadPDF}
        searchQuery={searchQuery}
        onSearch={setSearchQuery}
        matchCount={searchQuery.trim() ? matchCount : undefined}
        calloutMode={calloutMode}
        onCalloutMode={() => setCalloutMode(v => !v)}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Main area */}
        <div className="flex-1 overflow-y-auto p-4 flex justify-center">
          {isLoading && (
            <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
              Загрузка стойки…
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center h-64 text-red-400 text-sm">
              Ошибка загрузки данных
            </div>
          )}
          {!isLoading && !isError && (
            <RackView
              devices={rack}
              editMode={mode === 'edit'}
              calloutMode={calloutMode}
              callouts={callouts}
              highlightPortIds={highlightPortIds}
              onPortClick={handlePortClick}
              onReorder={handleReorder}
              onCompact={handleCompact}
              onDeviceCalloutClick={handleDeviceCalloutClick}
              onCalloutClick={handleCalloutClick}
            />
          )}
        </div>

        {/* Side panel */}
        {sidePanelOpen && selectedPort && selectedDevice && (
          <div className="w-80 shrink-0 flex flex-col border-l border-gray-800">
            <SidePanel
              port={selectedPort}
              device={selectedDevice}
              onClose={closeSidePanel}
              editMode={mode === 'edit'}
              onEdit={handleSidePanelEdit}
            />
          </div>
        )}
      </div>

      {editTarget && (
        <EditModal
          port={editTarget.port}
          device={editTarget.device}
          onClose={() => setEditTarget(null)}
        />
      )}

      {showRackManager && (
        <RackManagerModal onClose={() => setShowRackManager(false)} />
      )}

      {showHelp && (
        <HelpModal onClose={() => setShowHelp(false)} />
      )}

      {calloutTarget && (() => {
        const device = rack.find(d => d.id === calloutTarget.deviceId)
        if (!device) return null
        return (
          <CalloutModal
            device={device}
            existing={calloutTarget.existing}
            onSave={handleCalloutSave}
            onDelete={calloutTarget.existing ? handleCalloutDelete : undefined}
            onClose={() => setCalloutTarget(null)}
          />
        )
      })()}

      {showStats && (
        <StatsPanel devices={rack} onClose={() => setShowStats(false)} />
      )}
    </div>
  )
}
