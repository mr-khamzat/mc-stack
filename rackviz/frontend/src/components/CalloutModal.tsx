import React, { useState } from 'react'
import type { Callout, RackDevice } from '../types'

const COLORS: Array<{ key: string; label: string; hex: string }> = [
  { key: 'yellow', label: 'Внимание', hex: '#ca8a04' },
  { key: 'blue',   label: 'Инфо',     hex: '#3b82f6' },
  { key: 'red',    label: 'Критично', hex: '#dc2626' },
  { key: 'green',  label: 'Ок',       hex: '#16a34a' },
]

interface Props {
  device:    RackDevice
  existing?: Callout
  onSave:    (text: string, color: string) => void
  onDelete?: () => void
  onClose:   () => void
}

export const CalloutModal: React.FC<Props> = ({ device, existing, onSave, onDelete, onClose }) => {
  const [text,  setText]  = useState(existing?.text  ?? '')
  const [color, setColor] = useState(existing?.color ?? 'yellow')

  const handleSave = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSave(trimmed, color)
    onClose()
  }

  const handleDelete = () => {
    onDelete?.()
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 shadow-2xl">
        <h2 className="text-white font-semibold text-sm mb-1">
          💬 Аннотация
        </h2>
        <p className="text-gray-500 text-xs mb-3 truncate">
          {device.name}
        </p>

        {/* Color picker */}
        <div className="flex gap-2 mb-3">
          {COLORS.map(c => (
            <button
              key={c.key}
              title={c.label}
              onClick={() => setColor(c.key)}
              className="flex-1 rounded py-1.5 text-xs font-medium transition-all"
              style={{
                background:  color === c.key ? c.hex + '33' : '#1f2937',
                border:      `1.5px solid ${color === c.key ? c.hex : '#374151'}`,
                color:       c.hex,
              }}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Text area */}
        <textarea
          autoFocus
          value={text}
          onChange={e => setText(e.target.value)}
          rows={4}
          placeholder="Текст аннотации…"
          className="w-full bg-gray-800 text-gray-100 text-sm px-3 py-2 rounded border border-gray-600
            focus:outline-none focus:border-blue-500 resize-none mb-3 placeholder-gray-600"
        />

        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={!text.trim()}
            className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed
              text-white text-sm py-2 rounded"
          >
            Сохранить
          </button>
          {existing && onDelete && (
            <button
              onClick={handleDelete}
              className="px-3 text-red-400 hover:text-red-300 text-sm border border-red-900 hover:border-red-700 rounded"
            >
              🗑
            </button>
          )}
          <button
            onClick={onClose}
            className="px-3 text-gray-400 hover:text-white text-sm"
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}
