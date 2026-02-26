export type SourceType = 'free' | 'mc' | 'custom' | 'manual'
export type PortType   = 'rj45' | 'sfp' | 'uplink'
export type DeviceType = 'patch_panel' | 'switch' | 'hub' | 'router' | 'server' | 'poe_switch' | 'isp' | 'auth_router' | 'other'

export interface Port {
  id:              number
  device_id:       number
  port_number:     number
  port_type:       PortType
  source_type:     SourceType
  mc_node_id:      string | null
  mc_node_name:    string | null
  mc_node_online:  number
  custom_device_id: number | null
  manual_label:    string | null
  manual_type:     string | null
  manual_ip:       string | null
  manual_mac:      string | null
  manual_desc:     string | null
  label:           string | null
  description:     string | null
}

export interface RackDevice {
  id:          number
  name:        string
  device_type: DeviceType
  rack_unit:   number
  unit_size:   number
  port_count:  number
  port_type:   PortType
  color:       string
  notes:       string | null
  ports:       Port[]
}

export interface MCAgent {
  id:     string
  name:   string
  group:  string
  online: boolean
  os:     string
  ip:     string
  icon:   number
}

export interface WifiNeighbor {
  location: string
  ip:       string
  mac:      string
  name:     string
  type:     string
  iface:    string
}

export interface CustomDevice {
  id:          number
  name:        string
  device_type: string
  ip:          string | null
  mac:         string | null
  description: string | null
  location:    string | null
}

