import { useRef } from 'react'

export function TabBar({
  id,
  label,
  items,
  active,
  onChange,
}: {
  id: string
  label: string
  items: { id: string; label: string }[]
  active: string
  onChange: (id: string) => void
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([])
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => (
        <button
          key={item.id}
          ref={(element) => {
            buttons.current[index] = element
          }}
          type="button"
          role="tab"
          id={id + '-tab-' + item.id}
          aria-controls={id + '-panel'}
          aria-selected={active === item.id}
          tabIndex={active === item.id ? 0 : -1}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => {
            const next =
              event.key === 'ArrowRight'
                ? (index + 1) % items.length
                : event.key === 'ArrowLeft'
                  ? (index + items.length - 1) % items.length
                  : event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? items.length - 1
                      : null
            if (next === null) return
            event.preventDefault()
            const nextItem = items[next]
            if (!nextItem) return
            onChange(nextItem.id)
            buttons.current[next]?.focus()
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
