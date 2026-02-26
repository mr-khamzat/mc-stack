import React, { useState, useEffect } from 'react'
import { api } from '../api/client'
import { useRackStore } from '../store/useRackStore'

interface ToolbarProps {
  onManageRack?:     () => void
  onHelp?:           () => void
  onStats?:          () => void
  onDownloadPNG?:    () => void
  onDownloadPDF?:    () => void
  searchQuery?:      string
  onSearch?:         (q: string) => void
  matchCount?:       number
  calloutMode?:      boolean
  onCalloutMode?:    () => void
}

export const Toolbar: React.FC<ToolbarProps> = ({
  onManageRack, onHelp, onStats, onDownloadPNG, onDownloadPDF,
  searchQuery = '', onSearch, matchCount,
  calloutMode, onCalloutMode,
}) => {
  const {
    mode, isAdmin, setMode, setAdmin,
  } = useRackStore()
  const [showLogin, setShowLogin] = useState(false)

  // Auto-open login if redirected from netmap (?next=netmap)
  useEffect(() => {
    if (!isAdmin && new URLSearchParams(window.location.search).get('next') === 'netmap') {
      setShowLogin(true)
    }
  }, [isAdmin])

  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const login = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const r = await api.post('/auth/login', { username: user, password: pass })
      setAdmin(true, r.data.token)
      setShowLogin(false)
      setUser(''); setPass('')
      const next = new URLSearchParams(window.location.search).get('next')
      if (next === 'netmap') {
        window.location.href = '/netmap'
      }
    } catch {
      setError('Неверный логин или пароль')
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    setAdmin(false, null)
    setMode('view')
  }

  return (
    <>
      <div className="flex items-center gap-2 px-4 py-2 bg-gray-900 border-b border-gray-800 flex-wrap">
        {/* Logo */}
        <div className="flex items-center gap-2 mr-2">
          <span className="text-lg">🗄</span>
          <span className="font-bold text-white text-sm tracking-wide">RackViz</span>
        </div>

        {/* View / Edit toggle */}
        <div className="flex items-center bg-gray-800 rounded overflow-hidden border border-gray-700">
          <button
            onClick={() => setMode('view')}
            className={`px-3 py-1.5 text-xs font-medium transition-colors
              ${mode === 'view' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-gray-200'}`}
          >
            👁 Просмотр
          </button>
          {isAdmin && (
            <button
              onClick={() => setMode('edit')}
              className={`px-3 py-1.5 text-xs font-medium transition-colors
                ${mode === 'edit' ? 'bg-yellow-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
            >
              ✏ Редактировать
            </button>
          )}
        </div>

        {/* Edit mode extras */}
        {mode === 'edit' && (
          <>
            <span className="text-xs text-yellow-400 animate-pulse ml-1">
              ● Редактирование
            </span>
            <button
              onClick={onManageRack}
              className="text-xs px-3 py-1.5 rounded border border-gray-600 text-gray-300 hover:text-white hover:border-gray-400 bg-gray-800"
            >
              ⚙ Стойка
            </button>
          </>
        )}

        {/* Callout mode toggle (admin only) */}
        {isAdmin && (
          <button
            onClick={onCalloutMode}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
              calloutMode
                ? 'bg-purple-900 border-purple-600 text-purple-200'
                : 'border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 bg-gray-800'
            }`}
            title="Режим аннотаций — добавить подписи к устройствам"
          >
            💬 Аннотации
          </button>
        )}

        {/* Search box */}
        <div className="relative flex items-center ml-2">
          <span className="absolute left-2 text-gray-500 text-xs pointer-events-none">🔍</span>
          <input
            type="text"
            value={searchQuery}
            onChange={e => onSearch?.(e.target.value)}
            placeholder="Поиск порта…"
            className="bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 pl-6 pr-6 py-1.5
              focus:outline-none focus:border-blue-500 w-36 placeholder-gray-600"
          />
          {searchQuery && (
            <button
              onClick={() => onSearch?.('')}
              className="absolute right-1.5 text-gray-500 hover:text-white text-xs"
            >
              ×
            </button>
          )}
          {searchQuery && matchCount !== undefined && (
            <span className={`absolute -bottom-4 left-0 text-xs whitespace-nowrap ${matchCount > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
              {matchCount > 0 ? `${matchCount} найдено` : 'Не найдено'}
            </span>
          )}
        </div>

        <div className="flex-1" />

        {/* Stats button */}
        <button
          onClick={onStats}
          className="text-xs text-gray-400 hover:text-white px-2.5 py-1.5 rounded border border-gray-700 hover:border-gray-500 bg-gray-800"
          title="Статистика стойки"
        >
          📊
        </button>

        {/* Download PNG */}
        <button
          onClick={onDownloadPNG}
          className="text-xs text-gray-400 hover:text-white px-2.5 py-1.5 rounded border border-gray-700 hover:border-gray-500 bg-gray-800"
          title="Скачать PNG"
        >
          🖼 PNG
        </button>

        {/* Download PDF */}
        <button
          onClick={onDownloadPDF}
          className="text-xs text-gray-400 hover:text-white px-2.5 py-1.5 rounded border border-gray-700 hover:border-gray-500 bg-gray-800"
          title="Скачать PDF документацию стойки"
        >
          📄 PDF
        </button>

        {/* Auth */}
        {!isAdmin ? (
          <button
            onClick={() => setShowLogin(true)}
            className="text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded border border-gray-700 hover:border-gray-500"
          >
            🔑 Войти
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-green-400">● Admin</span>
            <button onClick={logout} className="text-xs text-gray-500 hover:text-gray-300">
              Выйти
            </button>
          </div>
        )}

        <a
          href="/netmap"
          target="_blank"
          className="text-xs text-gray-500 hover:text-blue-400 ml-1"
          title="Открыть карту сети"
        >
          🗺 NetMap
        </a>

        <button
          onClick={onHelp}
          className="text-xs text-gray-500 hover:text-white ml-1 w-6 h-6 rounded-full
            border border-gray-700 hover:border-gray-500 flex items-center justify-center"
          title="Инструкция"
        >
          ?
        </button>
      </div>

      {/* Login modal */}
      {showLogin && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70"
          onClick={e => e.target === e.currentTarget && setShowLogin(false)}
        >
          <form
            onSubmit={login}
            className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-80 shadow-2xl"
          >
            <h2 className="text-white font-semibold mb-1 text-sm">Вход администратора</h2>
            {new URLSearchParams(window.location.search).get('next') === 'netmap' && (
              <p className="text-yellow-400 text-xs mb-3">
                🗺 Войди чтобы открыть карту сети
              </p>
            )}
            <input
              autoFocus
              value={user}
              onChange={e => setUser(e.target.value)}
              placeholder="Логин"
              className="w-full bg-gray-800 text-white text-sm px-3 py-2 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500"
            />
            <input
              type="password"
              value={pass}
              onChange={e => setPass(e.target.value)}
              placeholder="Пароль"
              className="w-full bg-gray-800 text-white text-sm px-3 py-2 rounded border border-gray-600 mb-3 focus:outline-none focus:border-blue-500"
            />
            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={loading}
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm py-2 rounded"
              >
                {loading ? 'Вход…' : 'Войти'}
              </button>
              <button
                type="button"
                onClick={() => setShowLogin(false)}
                className="px-4 text-gray-400 hover:text-white text-sm"
              >
                Отмена
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
