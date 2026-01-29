import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Footer from '../Footer'

describe('Footer Component', () => {
  it('renders the footer with copyright text', () => {
    render(<Footer />)
    
    const copyrightText = screen.getByText(/© 2024 Email Campaigns Platform. All rights reserved./i)
    expect(copyrightText).toBeInTheDocument()
  })

  it('renders the footer element with correct class', () => {
    const { container } = render(<Footer />)
    
    const footer = container.querySelector('.footer')
    expect(footer).toBeInTheDocument()
  })

  it('contains navigation container', () => {
    const { container } = render(<Footer />)
    
    const navContainer = container.querySelector('.nav-container')
    expect(navContainer).toBeInTheDocument()
  })
})
