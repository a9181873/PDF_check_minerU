import { AuthUser } from '../stores/authStore';
import { httpClient as authApi } from './httpClient';

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export const authService = {
  async login(username: string, password: string): Promise<LoginResponse> {
    const res = await authApi.post<LoginResponse>('/api/auth/login', { username, password });
    return res.data;
  },

  async getMe(): Promise<AuthUser> {
    const res = await authApi.get<AuthUser>('/api/auth/me');
    return res.data;
  },

  async listUsers(): Promise<UserInfo[]> {
    const res = await authApi.get<UserInfo[]>('/api/auth/users');
    return res.data;
  },

  async createUser(data: { username: string; display_name: string; password: string; role: string }): Promise<UserInfo> {
    const res = await authApi.post<UserInfo>('/api/auth/users', data);
    return res.data;
  },

  async updateUser(userId: string, data: { display_name?: string; password?: string; role?: string; is_active?: boolean }): Promise<void> {
    await authApi.put(`/api/auth/users/${userId}`, data);
  },

  async deleteUser(userId: string): Promise<void> {
    await authApi.delete(`/api/auth/users/${userId}`);
  },
};

export default authService;
