import { createBrowserRouter } from 'react-router'

import { App } from '../App'
import { LoginPage } from '../pages/LoginPage'

export const applicationRouter = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        path: 'login',
        element: <LoginPage />,
      },
    ],
  },
])
