import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router/dom'

import { applicationRouter } from './app/router'
import './index.css'

const rootElement = document.getElementById('root')

if (rootElement === null) {
  throw new Error('Application root element was not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <RouterProvider router={applicationRouter} />
  </StrictMode>,
)
