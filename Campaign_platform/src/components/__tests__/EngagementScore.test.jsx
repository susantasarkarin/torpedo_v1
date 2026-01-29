import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import EngagementScore from '../EngagementScore'

describe('EngagementScore Component', () => {
  it('renders with default props', () => {
    render(<EngagementScore />)
    
    const scoreNumber = screen.getByText('0')
    expect(scoreNumber).toBeInTheDocument()
  })

  it('displays the correct score value', () => {
    render(<EngagementScore score={75} />)
    
    const scoreNumber = screen.getByText('75')
    expect(scoreNumber).toBeInTheDocument()
  })

  it('shows "Low" label for scores below 33', () => {
    render(<EngagementScore score={20} />)
    
    const label = screen.getByText('Low')
    expect(label).toBeInTheDocument()
  })

  it('shows "Medium" label for scores between 33 and 67', () => {
    render(<EngagementScore score={50} />)
    
    const label = screen.getByText('Medium')
    expect(label).toBeInTheDocument()
  })

  it('shows "High" label for scores above 67', () => {
    render(<EngagementScore score={85} />)
    
    const label = screen.getByText('High')
    expect(label).toBeInTheDocument()
  })

  it('displays breakdown metrics', () => {
    const breakdown = { opens: 60, clicks: 30, replies: 50 }
    render(<EngagementScore score={75} breakdown={breakdown} />)
    
    expect(screen.getByText('Opens')).toBeInTheDocument()
    expect(screen.getByText('60%')).toBeInTheDocument()
    expect(screen.getByText('Clicks')).toBeInTheDocument()
    expect(screen.getByText('30%')).toBeInTheDocument()
    expect(screen.getByText('Replies')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
  })

  it('shows "Improving" trend label when trend is up', () => {
    render(<EngagementScore score={75} trend="up" />)
    
    const trendLabel = screen.getByText('Improving')
    expect(trendLabel).toBeInTheDocument()
  })

  it('shows "Declining" trend label when trend is down', () => {
    render(<EngagementScore score={45} trend="down" />)
    
    const trendLabel = screen.getByText('Declining')
    expect(trendLabel).toBeInTheDocument()
  })

  it('shows "Stable" trend label when trend is stable', () => {
    render(<EngagementScore score={50} trend="stable" />)
    
    const trendLabel = screen.getByText('Stable')
    expect(trendLabel).toBeInTheDocument()
  })

  it('renders SVG circle elements', () => {
    const { container } = render(<EngagementScore score={75} />)
    
    const circles = container.querySelectorAll('circle')
    expect(circles).toHaveLength(2) // background and progress circles
  })
})
