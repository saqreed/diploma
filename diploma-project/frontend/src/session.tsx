import {createContext, useContext} from 'react'
import type {Account} from './api'
export const SessionContext = createContext<{account: Account | null; setAccount: (account: Account | null) => void}>({account: null, setAccount: () => {}})
export const useSession = () => useContext(SessionContext)
