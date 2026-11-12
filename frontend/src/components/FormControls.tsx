import {useId, useState} from 'react'
import {fieldLabel, type Field} from '../api'

export function DurationInput({value, onChange, optional=false, title='Период анализа', max=31536000}: {value:number|undefined;onChange:(v:number|undefined)=>void;optional?:boolean;title?:string;max?:number}) {
  const presets = [[600,'10 минут'],[3600,'1 час'],[86400,'24 часа'],[604800,'7 дней'],[2592000,'30 дней']] as const
  const [custom,setCustom]=useState(false)
  const [unit,setUnit]=useState(1)
  const standard=presets.some(([n])=>n===value)
  return <fieldset className="duration-control"><legend>{title}</legend>
    <select aria-label={title} value={custom || (value !== undefined && !standard) ? 'custom' : String(value ?? '')} onChange={e=>{if(e.target.value==='custom'){setCustom(true);setUnit(1)}else{setCustom(false);onChange(e.target.value ? Number(e.target.value):undefined)}}}>
      {optional && <option value="">Вся доступная история</option>}{!optional && value===undefined && <option value="">Выберите период</option>}
      {presets.filter(([n])=>n<=max).map(([n,t])=><option key={n} value={n}>{t}</option>)}<option value="custom">Свой период</option>
    </select>
    {(custom || (value!==undefined && !standard)) && <div className="duration-custom"><label>Число<input aria-label={title+' — число'} required type="number" min={1/unit} max={max/unit} step={1/unit} value={value===undefined?'':value/unit} onChange={e=>onChange(e.target.value ? Math.round(Number(e.target.value)*unit):undefined)}/></label><label>Единица<select aria-label={title+' — единица'} value={unit} onChange={e=>setUnit(Number(e.target.value))}>{[[1,'секунд'],[60,'минут'],[3600,'часов'],[86400,'дней']].map(([n,t])=><option key={n} value={n}>{t}</option>)}</select></label></div>}
    <small>{value===undefined?'Без ограничения давности':`Точное значение: ${value} с`}</small>
  </fieldset>
}

export function ValueItems({title='Значения',value,onChange,type='string'}:{title?:string;value:Array<string|number|boolean>;onChange:(v:Array<string|number|boolean>)=>void;type?:string}) {
  const [input,setInput]=useState('')
  const id=useId()
  const lines=input.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)
  const invalid=lines.filter(s=>type==='number' ? !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(s)||!Number.isFinite(Number(s)) : type==='boolean' ? !['true','false'].includes(s) : false)
  function add(){if(!invalid.length && lines.length){onChange([...value,...lines.map(s=>type==='boolean'?s==='true':s)]);setInput('')}}
  return <fieldset className="value-items"><legend>{title}</legend>
    <div className="value-chips">{value.map((v,i)=><span className="value-chip" key={i}><span>{String(v)}</span><button type="button" aria-label={`Удалить ${String(v)}`} onClick={()=>onChange(value.filter((_,j)=>i!==j))}>×</button></span>)}</div>
    <label htmlFor={id}>Добавить значения по одному или несколько строк</label><textarea id={id} value={input} rows={2} onChange={e=>{setInput(e.target.value);e.target.setCustomValidity(e.target.value.trim()?'Добавьте распознанные значения или очистите ввод':'')}} placeholder={type==='boolean'?'true или false — по одному на строку':'Каждая строка — отдельный элемент'}/>
    {input && <p className={invalid.length?'error':'muted'} role="status">{invalid.length?`Не распознаны: ${invalid.join('; ')}`:`Распознано: ${lines.join('; ')}`}</p>}
    <button type="button" disabled={!lines.length||Boolean(invalid.length)} onClick={e=>{add();e.currentTarget.form?.querySelector<HTMLTextAreaElement>('#'+CSS.escape(id))?.setCustomValidity('')}}>Добавить элементы</button>
    <small>Запятая внутри строки сохраняется. {type==='number'?'Числа хранятся без округления.':type==='boolean'?'Логические значения: true и false.':''}</small>
  </fieldset>
}

export function FieldSelect({title,value,fields,onChange}:{title:string;value:string|undefined;fields:Record<string,Field>;onChange:(v:string)=>void}) {
  const [search,setSearch]=useState('')
  const text=(n:string)=>`${fields[n]?.label || fieldLabel(n)} · ${n} · ${({number:'число',string:'строка',boolean:'да/нет'})[fields[n]!.type]} · ${fields[n]!.source==='DB'?'БД':'API'}`
  const options=Object.keys(fields).filter(n=>n===value||text(n).toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  return <div className="field-picker"><label>{title}<select aria-label={title} value={value??''} onChange={e=>onChange(e.target.value)}><option value="">Выберите поле</option>{value && !fields[value] && <option value={value}>{value} · нет в каталоге</option>}{options.map(n=><option key={n} value={n}>{text(n)}</option>)}</select></label><details><summary>Найти и вставить поле</summary><label>Поиск по имени, типу или источнику<input type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label><div className="field-results">{options.map(n=><button type="button" key={n} onClick={()=>onChange(n)}>{text(n)}</button>)}</div></details></div>
}
