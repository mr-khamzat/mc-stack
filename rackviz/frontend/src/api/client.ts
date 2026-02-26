import axios from 'axios'

export const api = axios.create({ baseURL: '/rack/api' })

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('rack_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})
