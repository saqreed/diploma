import { useEffect, useId, useRef, type ReactNode } from 'react'

export function SidePanel({
  title,
  onClose,
  children,
  returnFocus,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  returnFocus?: HTMLElement | null
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const previousFocus = returnFocus ?? document.activeElement
    if (!dialog.current?.open) dialog.current?.showModal()
    return () => {
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [returnFocus])

  return (
    <dialog
      ref={dialog}
      className="side-panel"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <header className="panel-heading">
        <h2 id={titleId}>{title}</h2>
        <button type="button" onClick={onClose} aria-label="Закрыть панель">
          Закрыть
        </button>
      </header>
      <div className="panel-body">{children}</div>
    </dialog>
  )
}
