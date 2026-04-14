import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from '../api/wordpress'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null)
  const [loading, setLoading] = useState(true)

  // Restore session on mount
  useEffect(() => {
    const token = localStorage.getItem('s3c_token')
    if (!token) { setLoading(false); return }
    getMe()
      .then(data => setUser(data))
      .catch(() => localStorage.removeItem('s3c_token'))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await apiLogin(email, password)
    localStorage.setItem('s3c_token', data.token)
    setUser(data)
    return data
  }, [])

  const register = useCallback(async (fields) => {
    const data = await apiRegister(fields)
    localStorage.setItem('s3c_token', data.token)
    setUser(data)
    return data
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    localStorage.removeItem('s3c_token')
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
