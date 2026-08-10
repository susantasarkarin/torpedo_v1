import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

/**
 * Landing page for the Unsubscribe link in panel email.
 *
 * The previous version POSTed to /api/panel/unsubscribe with no body and no
 * token, so the server had no address to act on — it set a localStorage flag
 * and then told the user "You have been unsubscribed", which was not true.
 * The opt-out link now carries a signed ?token identifying the recipient; that
 * token is what actually suppresses the address.
 */
export default function Unsubscribe() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const emailParam = searchParams.get('email') || ''

  const [state, setState] = useState('working') // working | done | unidentified
  const [manualEmail, setManualEmail] = useState('')

  const submit = async (payload) => {
    const res = await fetch('/api/panel/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error('request failed')
  }

  useEffect(() => {
    if (!token && !emailParam) {
      // No way to know who this is — ask, rather than claim success.
      setState('unidentified')
      return
    }
    (async () => {
      try {
        await submit(token ? { token } : { email: emailParam })
        setState('done')
      } catch {
        setState('unidentified')
      }
    })()
  }, [token, emailParam])

  const handleManualSubmit = async (e) => {
    e.preventDefault()
    if (!manualEmail.includes('@')) return
    try {
      await submit({ email: manualEmail })
    } catch {
      // The endpoint answers identically either way; treat it as accepted.
    }
    setState('done')
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="bg-white rounded-xl p-8 shadow-md max-w-xl w-full text-center">
        <h2 className="text-2xl font-bold mb-4">Unsubscribe</h2>

        {state === 'working' && (
          <p className="mb-4">Processing your unsubscribe request…</p>
        )}

        {state === 'done' && (
          <>
            <p className="mb-4">
              You've been unsubscribed. You will not receive further panel emails from us.
            </p>
            <Link to="/panel/login" className="panel-btn-primary">Back to Login</Link>
          </>
        )}

        {state === 'unidentified' && (
          <>
            <p className="mb-4 text-gray-600">
              We couldn't tell which address this link belongs to. Enter your email
              address and we'll remove it.
            </p>
            <form onSubmit={handleManualSubmit} className="flex flex-col gap-3">
              <input
                type="email"
                required
                value={manualEmail}
                onChange={(e) => setManualEmail(e.target.value)}
                placeholder="you@example.com"
                className="panel-form-input"
              />
              <button type="submit" className="panel-btn-primary">Unsubscribe me</button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
