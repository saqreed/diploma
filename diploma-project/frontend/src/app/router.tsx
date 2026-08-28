import { createBrowserRouter } from 'react-router'

import { App } from '../App'
import { DemoAppPage } from '../pages/DemoAppPage'
import { EnrollmentPage } from '../pages/EnrollmentPage'
import { LoginPage } from '../pages/LoginPage'
import { TotpPage } from '../pages/TotpPage'

export const applicationRouter = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        path: 'login',
        element: <LoginPage />,
      },
      {
        path: 'totp',
        element: <TotpPage />,
      },
      {
        path: 'enrollment',
        element: <EnrollmentPage />,
      },
      {
        path: 'demo',
        element: <DemoAppPage />,
      },
    ],
  },
])
