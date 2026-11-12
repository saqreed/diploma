import {fieldLabel, decimalText, valueText} from '../api'
export function Values({values}: {values: Record<string, unknown>}) {
  return <dl className="value-list">{Object.entries(values).map(([key,value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{key === 'registry_snapshot' ? <details><summary>Сохранённые строки реестра</summary><pre>{JSON.stringify(value,null,2)}</pre></details> : key === 'amount' ? decimalText(value) : valueText(value)}</dd></div>)}</dl>
}
