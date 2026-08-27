import { createBrowserRouter } from 'react-router'

import { App } from '../App'

export const applicationRouter = createBrowserRouter([
  {
    path: '/',
    element: <App />,
  },
])
