import axios from 'axios';

export const normalizeBase = (value?: string) => (value ? value.replace(/\/+$/, '') : '');
export const API_BASE = normalizeBase(import.meta.env.VITE_API_BASE);

export const httpClient = axios.create({
  baseURL: API_BASE || undefined,
  headers: { 'Content-Type': 'application/json' },
});

httpClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
