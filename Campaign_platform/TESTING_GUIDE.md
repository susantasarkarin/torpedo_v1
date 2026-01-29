# Frontend Testing Guide

This guide will help you test the frontend of the Campaign Platform application.

## Table of Contents
1. [Overview](#overview)
2. [Testing Stack](#testing-stack)
3. [Running Tests](#running-tests)
4. [Writing Tests](#writing-tests)
5. [Best Practices](#best-practices)
6. [Examples](#examples)

---

## Overview

The Campaign Platform frontend is built with **React** and **Vite**, and uses **Vitest** as the testing framework. This setup provides fast, efficient testing with excellent developer experience.

## Testing Stack

- **[Vitest](https://vitest.dev/)** - Fast unit test framework (Vite-native)
- **[React Testing Library](https://testing-library.com/react)** - React component testing utilities
- **[@testing-library/jest-dom](https://github.com/testing-library/jest-dom)** - Custom matchers for DOM assertions
- **[@testing-library/user-event](https://testing-library.com/docs/user-event/intro)** - Simulates user interactions
- **[jsdom](https://github.com/jsdom/jsdom)** - DOM implementation for Node.js

## Running Tests

### Available Commands

```bash
# Run tests in watch mode (recommended for development)
npm test

# Run all tests once
npm run test:run

# Run tests with UI dashboard
npm run test:ui

# Run tests with coverage report
npm run test:coverage
```

### Watch Mode
When you run `npm test`, Vitest will run in watch mode. This means:
- Tests automatically re-run when you change files
- Only changed tests run (smart mode)
- Interactive CLI for filtering tests

### Coverage Reports
Run `npm run test:coverage` to generate a coverage report. This will create:
- Terminal summary of coverage
- HTML report in `coverage/` directory
- Open `coverage/index.html` in your browser to see detailed coverage

---

## Writing Tests

### Test File Location

Tests should be placed in one of two locations:

1. **Component Tests**: Next to the component in a `__tests__` folder
   ```
   src/components/
   ├── Footer.jsx
   └── __tests__/
       └── Footer.test.jsx
   ```

2. **Integration Tests**: In the `src/test/integration/` folder
   ```
   src/test/integration/
   └── App.test.jsx
   ```

### Test File Naming

- Use `.test.jsx` or `.test.js` extension
- Match the component name: `ComponentName.test.jsx`

### Basic Test Structure

```javascript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import YourComponent from '../YourComponent'

describe('YourComponent', () => {
  it('should render correctly', () => {
    render(<YourComponent />)
    
    const element = screen.getByText('Some text')
    expect(element).toBeInTheDocument()
  })
})
```

### Testing Components with Router

For components that use React Router, use the `renderWithRouter` helper:

```javascript
import { renderWithRouter } from '../../test/test-utils'
import YourComponent from '../YourComponent'

describe('YourComponent with Router', () => {
  it('should render with routing', () => {
    renderWithRouter(<YourComponent />)
    // Your assertions here
  })
})
```

---

## Best Practices

### 1. **Test User Behavior, Not Implementation**
Focus on what the user sees and does, not internal component logic.

```javascript
// ✅ Good - Tests user-visible behavior
expect(screen.getByRole('button', { name: /submit/i })).toBeInTheDocument()

// ❌ Avoid - Tests implementation details
expect(component.state.isSubmitting).toBe(false)
```

### 2. **Use Accessible Queries**
Prefer queries that reflect how users interact with your app:

Priority order:
1. `getByRole` - Accessible to assistive technologies
2. `getByLabelText` - For form elements
3. `getByPlaceholderText` - Form inputs
4. `getByText` - Non-interactive elements
5. `getByTestId` - Last resort

```javascript
// ✅ Best
screen.getByRole('button', { name: /submit/i })

// ✅ Good for forms
screen.getByLabelText(/email address/i)

// ⚠️ Use sparingly
screen.getByTestId('submit-button')
```

### 3. **Keep Tests Isolated**
Each test should be independent and not rely on other tests.

```javascript
describe('Counter Component', () => {
  it('starts at 0', () => {
    render(<Counter />)
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('increments when clicked', async () => {
    const user = userEvent.setup()
    render(<Counter />)
    
    await user.click(screen.getByRole('button', { name: /increment/i }))
    expect(screen.getByText('1')).toBeInTheDocument()
  })
})
```

### 4. **Use Descriptive Test Names**
Test names should clearly describe what is being tested.

```javascript
// ✅ Good
it('displays error message when email is invalid', () => {})
it('submits form data when user clicks submit button', () => {})

// ❌ Avoid
it('works correctly', () => {})
it('test 1', () => {})
```

### 5. **Mock External Dependencies**
Mock API calls, external libraries, and other side effects.

```javascript
import { vi } from 'vitest'

// Mock an API call
vi.mock('../../api/user', () => ({
  fetchUser: vi.fn(() => Promise.resolve({ name: 'John Doe' }))
}))
```

---

## Examples

### Example 1: Testing a Simple Component

```javascript
// src/components/__tests__/Button.test.jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Button from '../Button'

describe('Button Component', () => {
  it('renders with correct text', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByRole('button', { name: /click me/i })).toBeInTheDocument()
  })

  it('calls onClick handler when clicked', async () => {
    const handleClick = vi.fn()
    const user = userEvent.setup()
    
    render(<Button onClick={handleClick}>Click me</Button>)
    
    await user.click(screen.getByRole('button'))
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Click me</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })
})
```

### Example 2: Testing a Form

```javascript
// src/components/__tests__/LoginForm.test.jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LoginForm from '../LoginForm'

describe('LoginForm Component', () => {
  it('submits form with correct data', async () => {
    const handleSubmit = vi.fn()
    const user = userEvent.setup()
    
    render(<LoginForm onSubmit={handleSubmit} />)
    
    // Fill in the form
    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/password/i), 'password123')
    
    // Submit
    await user.click(screen.getByRole('button', { name: /login/i }))
    
    expect(handleSubmit).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password123'
    })
  })

  it('displays validation error for invalid email', async () => {
    const user = userEvent.setup()
    
    render(<LoginForm />)
    
    await user.type(screen.getByLabelText(/email/i), 'invalid-email')
    await user.click(screen.getByRole('button', { name: /login/i }))
    
    expect(screen.getByText(/invalid email address/i)).toBeInTheDocument()
  })
})
```

### Example 3: Testing with Mocked API

```javascript
// src/components/__tests__/UserProfile.test.jsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import UserProfile from '../UserProfile'
import * as userApi from '../../api/user'

// Mock the API module
vi.mock('../../api/user')

describe('UserProfile Component', () => {
  beforeEach(() => {
    // Reset mocks before each test
    vi.clearAllMocks()
  })

  it('displays user data when loaded', async () => {
    // Setup mock response
    userApi.fetchUser.mockResolvedValue({
      name: 'John Doe',
      email: 'john@example.com'
    })

    render(<UserProfile userId="123" />)

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
      expect(screen.getByText('john@example.com')).toBeInTheDocument()
    })
  })

  it('displays error message when API fails', async () => {
    // Setup mock error
    userApi.fetchUser.mockRejectedValue(new Error('Failed to fetch'))

    render(<UserProfile userId="123" />)

    await waitFor(() => {
      expect(screen.getByText(/error loading user/i)).toBeInTheDocument()
    })
  })
})
```

### Example 4: Testing Async Behavior

```javascript
// src/components/__tests__/SearchBar.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SearchBar from '../SearchBar'

describe('SearchBar Component', () => {
  it('shows loading state while searching', async () => {
    const handleSearch = vi.fn(() => new Promise(resolve => 
      setTimeout(resolve, 100)
    ))
    const user = userEvent.setup()

    render(<SearchBar onSearch={handleSearch} />)

    await user.type(screen.getByRole('textbox'), 'test query')
    await user.click(screen.getByRole('button', { name: /search/i }))

    // Check for loading state
    expect(screen.getByText(/searching/i)).toBeInTheDocument()

    // Wait for search to complete
    await waitFor(() => {
      expect(screen.queryByText(/searching/i)).not.toBeInTheDocument()
    })
  })
})
```

---

## Common Testing Patterns

### Testing Conditional Rendering

```javascript
it('shows success message when operation succeeds', () => {
  render(<Component status="success" />)
  expect(screen.getByText(/operation successful/i)).toBeInTheDocument()
})

it('does not show success message when operation fails', () => {
  render(<Component status="error" />)
  expect(screen.queryByText(/operation successful/i)).not.toBeInTheDocument()
})
```

### Testing Lists

```javascript
it('renders list of items', () => {
  const items = ['Item 1', 'Item 2', 'Item 3']
  render(<List items={items} />)
  
  items.forEach(item => {
    expect(screen.getByText(item)).toBeInTheDocument()
  })
})
```

### Testing CSS Classes

```javascript
it('applies correct CSS class when active', () => {
  const { container } = render(<Component active={true} />)
  expect(container.firstChild).toHaveClass('active')
})
```

---

## Debugging Tests

### 1. Use `screen.debug()`
Print the current DOM state:

```javascript
it('debug test', () => {
  render(<Component />)
  screen.debug() // Prints the entire DOM
  screen.debug(screen.getByRole('button')) // Prints specific element
})
```

### 2. Use Vitest UI
Run `npm run test:ui` to open an interactive test UI in your browser. This provides:
- Visual test runner
- DOM inspector
- Error stack traces
- Test timeline

### 3. Check Available Queries
If you can't find an element, check what's available:

```javascript
screen.logTestingPlaygroundURL() // Generates URL to testing playground
```

---

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: npm run test:run

- name: Generate coverage
  run: npm run test:coverage
```

---

## Additional Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library Docs](https://testing-library.com/docs/react-testing-library/intro/)
- [Testing Library Cheatsheet](https://testing-library.com/docs/react-testing-library/cheatsheet)
- [Common Testing Mistakes](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)

---

## Getting Help

If you have questions or run into issues:

1. Check the test output for error messages
2. Use `screen.debug()` to inspect the DOM
3. Review this guide and the official documentation
4. Run tests with `--reporter=verbose` for detailed output

Happy testing! 🚀
