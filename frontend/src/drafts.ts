import {useEffect, useState, type Dispatch, type SetStateAction} from 'react'
// Volatile UI drafts only. No browser persistence, no secrets on disk.
const drafts=new Map<string,unknown>()
export function clearMemoryDrafts(){drafts.clear()}
export function useMemoryDraft<T>(key:string,initial:T):[T,Dispatch<SetStateAction<T>>]{
  const [value,setValue]=useState<T>(()=>drafts.has(key)?drafts.get(key) as T:initial)
  useEffect(()=>{drafts.set(key,value)},[key,value])
  return [value,setValue]
}
