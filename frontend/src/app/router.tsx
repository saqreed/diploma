import { createBrowserRouter, Navigate } from 'react-router'

import { App } from '../App'
import { RulesPage } from '../pages/RulesPage'
import { ExpensesPage } from '../pages/ExpensesPage'
import { SettingsPage } from '../pages/SettingsPage'
import { SignInPage } from '../pages/SignInPage'
import { JournalPage } from '../pages/JournalPage'

export const applicationRouter = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        path: 'login',
        element: <SignInPage />,
      },
      {
        path: 'journal',
        element: <JournalPage />,
      },
      {
        path: 'settings',
        element: <SettingsPage />,
      },
      {
        path: 'demo',
        element: <ExpensesPage />,
      },
      {
        path: 'admin',
        element: <RulesPage />,
      },
      {index: true, element: <Navigate to="/login" replace />},
      {path: '*', element: <Navigate to="/login" replace />},
    ],
  },
])
