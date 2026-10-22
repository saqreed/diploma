type Name = 'shield' | 'rules' | 'apps' | 'journal' | 'expenses' | 'user' | 'arrow'
const paths: Record<Name, string> = {
  shield: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6',
  rules: 'M6 3h8l4 4v14H6V3Zm8 0v5h4M9 12h6m-6 4h4',
  apps: 'M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z',
  journal: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  expenses: 'M4 7h16v14H4V7Zm4 0V3h8v4M4 12h16m-10 0v3h4v-3',
  user: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a8 8 0 0 1 16 0v3H4Z',
  arrow: 'm9 5 7 7-7 7',
}
export function Icon({name}: {name: Name}) {
  return <svg className={'icon icon-' + name} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>
}
