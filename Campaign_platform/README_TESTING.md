# Testing the Campaign Platform Frontend

Welcome! This guide will help you get started with testing the frontend of the Campaign Platform application.

## ✅ Yes, You Can Test the Frontend!

This application now has a complete frontend testing setup using modern tools and best practices.

## Quick Start

### 1. Install Dependencies (if not already done)

```bash
cd Campaign_platform
npm install
```

### 2. Run Tests

```bash
# Run tests in watch mode (recommended for development)
npm test

# Run all tests once
npm run test:run

# Run tests with coverage report
npm run test:coverage

# Run tests with interactive UI
npm run test:ui
```

## What's Included?

### Testing Framework
- ✅ **Vitest** - Fast, modern test runner optimized for Vite
- ✅ **React Testing Library** - Best practices for testing React components
- ✅ **jsdom** - DOM implementation for Node.js
- ✅ **User Event** - Realistic user interaction simulation

### Example Tests
We've included several example tests to get you started:

1. **Component Tests** (`src/components/__tests__/`)
   - Footer.test.jsx - Simple component testing
   - EngagementScore.test.jsx - Testing components with props and logic
   - ui/Button.test.jsx - Comprehensive testing (31 tests covering all scenarios)

2. **Integration Tests** (`src/test/integration/`)
   - App.test.jsx - Testing app-level functionality

3. **Test Utilities** (`src/test/`)
   - setup.js - Test configuration
   - test-utils.jsx - Custom render helpers for components with providers

## Test Coverage

Currently, we have **46 passing tests** covering:
- Component rendering
- User interactions
- Props and state
- Styling and variants
- Accessibility
- Edge cases

To see detailed coverage:
```bash
npm run test:coverage
```

Open `coverage/index.html` in your browser for an interactive coverage report.

## Documentation

We've created two comprehensive guides:

### 1. **TESTING_GUIDE.md** - Complete Testing Guide
Comprehensive documentation covering:
- Testing stack overview
- How to write tests
- Best practices
- Common patterns
- Debugging tips
- Many code examples

### 2. **TESTING_QUICK_START.md** - Quick Reference
Quick reference guide with:
- Common test patterns
- Query examples
- Assertion examples
- Cheat sheet format

## Writing Your First Test

1. Create a test file next to your component:
   ```
   src/components/
   ├── MyComponent.jsx
   └── __tests__/
       └── MyComponent.test.jsx
   ```

2. Write a simple test:
   ```javascript
   import { describe, it, expect } from 'vitest'
   import { render, screen } from '@testing-library/react'
   import MyComponent from '../MyComponent'

   describe('MyComponent', () => {
     it('should render', () => {
       render(<MyComponent />)
       expect(screen.getByText('Hello')).toBeInTheDocument()
     })
   })
   ```

3. Run the test:
   ```bash
   npm test
   ```

## Example Test Run Output

```
✓ src/components/ui/__tests__/Button.test.jsx (31 tests) 485ms
✓ src/components/__tests__/EngagementScore.test.jsx (10 tests) 94ms
✓ src/components/__tests__/Footer.test.jsx (3 tests) 53ms
✓ src/test/integration/App.test.jsx (2 tests) 45ms

Test Files  4 passed (4)
     Tests  46 passed (46)
```

## Testing Workflow

1. **Development Mode**: Run `npm test` to watch files
2. **Before Commit**: Run `npm run test:run` to ensure all tests pass
3. **Coverage Check**: Run `npm run test:coverage` to check coverage
4. **Interactive Debugging**: Run `npm run test:ui` for visual debugging

## Best Practices

1. ✅ Test user behavior, not implementation
2. ✅ Use accessible queries (`getByRole`, `getByLabelText`)
3. ✅ Keep tests isolated and independent
4. ✅ Use descriptive test names
5. ✅ Mock external dependencies
6. ✅ Test edge cases and error states

## Common Testing Patterns

### Testing User Interactions
```javascript
import userEvent from '@testing-library/user-event'

it('handles button click', async () => {
  const user = userEvent.setup()
  render(<Button onClick={handleClick}>Click me</Button>)
  await user.click(screen.getByRole('button'))
  expect(handleClick).toHaveBeenCalled()
})
```

### Testing Forms
```javascript
it('submits form with data', async () => {
  const user = userEvent.setup()
  render(<LoginForm onSubmit={handleSubmit} />)
  
  await user.type(screen.getByLabelText(/email/i), 'test@example.com')
  await user.click(screen.getByRole('button', { name: /submit/i }))
  
  expect(handleSubmit).toHaveBeenCalled()
})
```

### Testing Async Operations
```javascript
it('shows data after loading', async () => {
  render(<UserProfile />)
  
  const userName = await screen.findByText('John Doe')
  expect(userName).toBeInTheDocument()
})
```

## Need Help?

1. Check **TESTING_GUIDE.md** for detailed examples
2. Check **TESTING_QUICK_START.md** for quick reference
3. Run `npm run test:ui` for interactive debugging
4. Use `screen.debug()` to inspect the DOM in tests

## CI/CD Integration

Tests can be integrated into your CI/CD pipeline:

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: npm run test:run
  
- name: Generate coverage
  run: npm run test:coverage
```

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [Testing Library Cheatsheet](https://testing-library.com/docs/react-testing-library/cheatsheet)

---

## Summary

**Yes, you can test the frontend!** 🎉

- ✅ Complete testing framework installed
- ✅ 46 example tests running
- ✅ Comprehensive documentation provided
- ✅ Ready for development and CI/CD

Start by running `npm test` and exploring the example tests!

Happy testing! 🚀
