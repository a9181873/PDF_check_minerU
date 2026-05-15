import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: 'admin' | 'reviewer';
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;

  setAuth: (token: string, user: AuthUser) => void;
  logout: () => void;
  loadFromStorage: () => void;
}

const readStoredAuth = () => {
  const token = localStorage.getItem('auth_token');
  const userStr = localStorage.getItem('auth_user');
  if (!token || !userStr) {
    return null;
  }

  try {
    return {
      token,
      user: JSON.parse(userStr) as AuthUser,
    };
  } catch {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    return null;
  }
};

export const useAuthStore = create<AuthState>()(
  devtools(
    (set) => {
      const storedAuth = readStoredAuth();

      return {
        token: storedAuth?.token ?? null,
        user: storedAuth?.user ?? null,
        isAuthenticated: Boolean(storedAuth),

        setAuth: (token, user) => {
          localStorage.setItem('auth_token', token);
          localStorage.setItem('auth_user', JSON.stringify(user));
          set({ token, user, isAuthenticated: true });
        },

        logout: () => {
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_user');
          set({ token: null, user: null, isAuthenticated: false });
        },

        loadFromStorage: () => {
          const stored = readStoredAuth();
          if (stored) {
            set({ token: stored.token, user: stored.user, isAuthenticated: true });
          } else {
            set({ token: null, user: null, isAuthenticated: false });
          }
        },
      };
    },
    { name: 'auth-store' }
  )
);
