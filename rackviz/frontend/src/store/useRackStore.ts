import { create } from 'zustand'
import type { Port, RackDevice } from '../types'

type Mode = 'view' | 'edit'

interface RackStore {
  mode:           Mode
  isAdmin:        boolean
  token:          string | null
  selectedPort:   Port | null
  selectedDevice: RackDevice | null
  sidePanelOpen:  boolean

  setMode:        (m: Mode) => void
  setAdmin:       (v: boolean, token: string | null) => void
  selectPort:     (p: Port | null, d: RackDevice | null) => void
  closeSidePanel: () => void
}

export const useRackStore = create<RackStore>((set) => ({
  mode:           'view',
  isAdmin:        false,
  token:          localStorage.getItem('rack_token'),
  selectedPort:   null,
  selectedDevice: null,
  sidePanelOpen:  false,

  setMode: (m) => set({ mode: m }),

  setAdmin: (v, token) => {
    if (token) localStorage.setItem('rack_token', token)
    else       localStorage.removeItem('rack_token')
    set({ isAdmin: v, token })
  },

  selectPort: (p, d) => set({
    selectedPort:   p,
    selectedDevice: d,
    sidePanelOpen:  p !== null,
  }),

  closeSidePanel: () => set({ selectedPort: null, sidePanelOpen: false }),
}))
