# Frontend Testing - Quick Start Guide

## 🚀 Get Started in 3 Steps

### 1. Run Tests

```bash
# Watch mode (recommended for development)
npm test

# Run all tests once
npm run test:run

# Run with coverage
npm run test:coverage

# Run with UI dashboard
npm run test:ui
```

### 2. Write Your First Test

Create a file: `src/components/__tests__/MyComponent.test.jsx`

```javascript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MyComponent from '../MyComponent'

describe('MyComponent', () => {
  it('should render text', () => {
    render(<MyComponent />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })
})
```

### 3. Run Your Test

```bash
npm test
```

## 📝 Common Test Patterns

### Testing Text Content

```javascript
// Find by exact text
screen.getByText('Submit')

// Find by regex (case-insensitive)
screen.getByText(/submit/i)

// Find by partial text
screen.getByText(/ubmi/)
```

### Testing Buttons

```javascript
// Find button by accessible name
screen.getByRole('button', { name: /submit/i })

// Check if button is disabled
expect(screen.getByRole('button')).toBeDisabled()

// Click a button
import userEvent from '@testing-library/user-event'

const user = userEvent.setup()
await user.click(screen.getByRole('button'))
```

### Testing Forms

```javascript
import userEvent from '@testing-library/user-event'

const user = userEvent.setup()

// Type in input
await user.type(screen.getByLabelText(/email/i), 'test@example.com')

// Select option
await user.selectOptions(screen.getByRole('combobox'), 'Option 1')

// Submit form
await user.click(screen.getByRole('button', { name: /submit/i }))
```

### Testing Async Operations

```javascript
import { waitFor } from '@testing-library/react'

// Wait for element to appear
await waitFor(() => {
  expect(screen.getByText(/success/i)).toBeInTheDocument()
})

// Or use findBy (automatically waits)
const successMessage = await screen.findByText(/success/i)
expect(successMessage).toBeInTheDocument()
```

### Mocking Functions

```javascript
import { vi } from 'vitest'

// Create a mock function
const handleClick = vi.fn()

render(<Button onClick={handleClick}>Click me</Button>)

// Verify it was called
expect(handleClick).toHaveBeenCalled()
expect(handleClick).toHaveBeenCalledTimes(1)
```

## 🔍 Finding Elements Priority

Use queries in this order:

1. **getByRole** - Most accessible
   ```javascript
   screen.getByRole('button', { name: /submit/i })
   ```

2. **getByLabelText** - For form fields
   ```javascript
   screen.getByLabelText(/email/i)
   ```

3. **getByPlaceholderText** - For inputs
   ```javascript
   screen.getByPlaceholderText(/enter email/i)
   ```

4. **getByText** - For non-interactive content
   ```javascript
   screen.getByText(/welcome/i)
   ```

5. **getByTestId** - Last resort
   ```javascript
   screen.getByTestId('custom-element')
   ```

## 🎯 Query Variants

- **getBy** - Throws error if not found (use for elements that should exist)
- **queryBy** - Returns null if not found (use to test element doesn't exist)
- **findBy** - Async, waits for element (use for async content)

```javascript
// Element must exist
const button = screen.getByRole('button')

// Check element doesn't exist
expect(screen.queryByText('Error')).not.toBeInTheDocument()

// Wait for element to appear
const message = await screen.findByText('Loaded!')
```

## 🎨 Common Assertions

```javascript
// Element exists
expect(element).toBeInTheDocument()

// Element is visible
expect(element).toBeVisible()

// Element is disabled
expect(element).toBeDisabled()

// Element has text
expect(element).toHaveTextContent('Hello')

// Element has class
expect(element).toHaveClass('active')

// Element has attribute
expect(element).toHaveAttribute('href', '/home')
```

## 🛠️ Debugging Tips

### 1. Print DOM

```javascript
screen.debug() // Print entire DOM
screen.debug(element) // Print specific element
```

### 2. Use Vitest UI

```bash
npm run test:ui
```

Opens interactive UI in browser with:
- Visual test results
- DOM inspector
- Time travel debugging

### 3. Check Available Queries

```javascript
screen.logTestingPlaygroundURL()
```

Generates URL showing all available queries for current DOM.

## 📁 Test File Structure

```
src/
├── components/
│   ├── Button.jsx
│   └── __tests__/
│       └── Button.test.jsx
├── pages/
│   ├── Dashboard.jsx
│   └── __tests__/
│       └── Dashboard.test.jsx
└── test/
    ├── setup.js (test configuration)
    ├── test-utils.jsx (custom helpers)
    └── integration/
        └── App.test.jsx
```

## 📊 Coverage Reports

```bash
npm run test:coverage
```

Creates coverage report in `coverage/` directory.

Open `coverage/index.html` in browser to see detailed report.

## 🎓 Learn More

For detailed examples and best practices, see:
- [TESTING_GUIDE.md](./TESTING_GUIDE.md)
- [Vitest Docs](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)

---

**Need Help?** Check the full [TESTING_GUIDE.md](./TESTING_GUIDE.md) for comprehensive examples and patterns.
