import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Shield, Trash2, UserCog, X } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { authService, UserInfo } from '../services/authApi';

const AdminPage: React.FC = () => {
  const navigate = useNavigate();
  const { user: currentUser, logout } = useAuthStore();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ username: '', display_name: '', password: '', role: 'reviewer' });
  const [editForm, setEditForm] = useState({ display_name: '', password: '', role: '', is_active: true });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    try { setUsers(await authService.listUsers()); } catch { setError('載入帳號清單失敗'); }
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  useEffect(() => {
    if (currentUser?.role !== 'admin') navigate('/');
  }, [currentUser, navigate]);

  const handleCreate = async () => {
    if (creating) return;
    setError(null);
    if (!form.username || !form.display_name || !form.password) { setError('所有欄位皆為必填'); return; }
    setCreating(true);
    try {
      await authService.createUser(form);
      setForm({ username: '', display_name: '', password: '', role: 'reviewer' });
      setShowCreate(false);
      await loadUsers();
    } catch { setError('建立失敗，帳號可能已存在'); }
    finally { setCreating(false); }
  };

  const handleUpdate = async (userId: string) => {
    if (updatingId) return;
    setUpdatingId(userId);
    try {
      const payload: { display_name?: string; password?: string; role?: string; is_active?: boolean } = {};
      if (editForm.display_name) payload.display_name = editForm.display_name;
      if (editForm.password) payload.password = editForm.password;
      if (editForm.role) payload.role = editForm.role;
      payload.is_active = editForm.is_active;
      await authService.updateUser(userId, payload);
      setEditId(null);
      await loadUsers();
    } catch { setError('更新失敗'); }
    finally { setUpdatingId(null); }
  };

  const handleDelete = async (userId: string) => {
    if (deletingId) return;
    if (!confirm('確定要刪除此帳號？')) return;
    setDeletingId(userId);
    try {
      await authService.deleteUser(userId);
      await loadUsers();
    } catch { setError('刪除失敗'); }
    finally { setDeletingId(null); }
  };

  const startEdit = (u: UserInfo) => {
    setEditId(u.id);
    setEditForm({ display_name: u.display_name, password: '', role: u.role, is_active: !!u.is_active });
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(0,153,68,0.10),_transparent_38%),linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)] p-4 sm:p-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="p-2 rounded-xl hover:bg-white/80 transition-colors"><ArrowLeft size={20} /></button>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2"><Shield size={24} className="text-primary-600" />帳號管理</h1>
              <p className="text-sm text-gray-500">管理系統使用者帳號與權限</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">{currentUser?.display_name}</span>
            <button onClick={() => { logout(); navigate('/login'); }} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">登出</button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)}><X size={16} /></button>
          </div>
        )}

        {/* Create button */}
        <div className="mb-6">
          <button onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors text-sm font-medium">
            <Plus size={16} /><span>新增帳號</span>
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="mb-6 bg-white/95 rounded-2xl border border-white shadow-large p-6 backdrop-blur animate-fade-in">
            <h3 className="font-medium text-gray-900 mb-4">新增帳號</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="帳號" className="px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm" />
              <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="顯示名稱" className="px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm" />
              <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="密碼" className="px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm" />
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm bg-white">
                <option value="reviewer">審核人員</option>
                <option value="admin">管理員</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button onClick={handleCreate} disabled={creating} className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm disabled:opacity-60 disabled:cursor-not-allowed">{creating ? '建立中…' : '建立'}</button>
              <button onClick={() => setShowCreate(false)} disabled={creating} className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm disabled:opacity-60">取消</button>
            </div>
          </div>
        )}

        {/* User list */}
        <div className="bg-white/95 rounded-[28px] shadow-large border border-white p-6 backdrop-blur">
          <h3 className="font-medium text-gray-900 mb-4 flex items-center gap-2"><UserCog size={18} />帳號列表 ({users.length})</h3>
          <div className="space-y-3">
            {users.map((u) => (
              <div key={u.id} className={`p-4 rounded-xl border transition-colors ${u.is_active ? 'bg-gray-50 border-gray-100' : 'bg-gray-100 border-gray-200 opacity-60'}`}>
                {editId === u.id ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <input value={editForm.display_name} onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })} placeholder="顯示名稱" className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                      <input type="password" value={editForm.password} onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} placeholder="新密碼 (不修改留空)" className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                      <select value={editForm.role} onChange={(e) => setEditForm({ ...editForm, role: e.target.value })} className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                        <option value="reviewer">審核人員</option>
                        <option value="admin">管理員</option>
                      </select>
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={editForm.is_active} onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })} className="rounded" />啟用帳號
                      </label>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => handleUpdate(u.id)} disabled={updatingId === u.id} className="px-3 py-1.5 bg-primary-600 text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-60 disabled:cursor-not-allowed">{updatingId === u.id ? '儲存中…' : '儲存'}</button>
                      <button onClick={() => setEditId(null)} disabled={updatingId === u.id} className="px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-60">取消</button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div>
                        <div className="font-medium text-gray-900">{u.display_name}</div>
                        <div className="text-xs text-gray-500">@{u.username}</div>
                      </div>
                      <span className={`text-xs px-2 py-1 rounded-full font-medium ${u.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                        {u.role === 'admin' ? '管理員' : '審核人員'}
                      </span>
                      {!u.is_active && <span className="text-xs px-2 py-1 rounded-full bg-gray-200 text-gray-600">已停用</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => startEdit(u)} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors">編輯</button>
                      {u.id !== currentUser?.id && (
                        <button onClick={() => handleDelete(u.id)} disabled={deletingId === u.id} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-60 disabled:cursor-not-allowed"><Trash2 size={16} /></button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminPage;
