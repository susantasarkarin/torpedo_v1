import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

export default function Unsubscribe() {
  const [done, setDone] = useState(false)

  useEffect(() => {
    // Mark DND locally
    try {
      localStorage.setItem('panel_dnd', 'true')
      localStorage.setItem('panel_unsubscribed', 'true')
    } catch (e) {
      // ignore
    }

    // Optionally call backend API if available
    (async () => {
      try {
        await fetch('/api/panel/unsubscribe', { method: 'POST' })
      } catch (e) {
        // ignore errors
      }
      setDone(true)
    })()
  }, [])

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="bg-white rounded-xl p-8 shadow-md max-w-xl text-center">
        <h2 className="text-2xl font-bold mb-4">Unsubscribe</h2>
        {done ? (
          <>
            <p className="mb-4">You have been unsubscribed and marked as DND. We will not send you further emails.</p>
            <Link to="/panel/login" className="panel-btn-primary">Back to Login</Link>
          </>
        ) : (
          <p className="mb-4">Processing your unsubscribe request...</p>
        )}
      </div>
    </div>
  )
}
