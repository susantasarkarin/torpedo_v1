import { render } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

/**
 * Custom render function that includes common providers
 * Use this for components that need routing context
 */
export function renderWithRouter(ui, options = {}) {
  return render(ui, {
    wrapper: ({ children }) => (
      <BrowserRouter>
        {children}
      </BrowserRouter>
    ),
    ...options,
  })
}

/**
 * Custom render function for components that need multiple providers
 * Extend this as needed with other providers (theme, auth, etc.)
 */
export function renderWithProviders(ui, options = {}) {
  const AllProviders = ({ children }) => {
    return (
      <BrowserRouter>
        {children}
      </BrowserRouter>
    )
  }

  return render(ui, { wrapper: AllProviders, ...options })
}

// Re-export everything from React Testing Library
export * from '@testing-library/react'
