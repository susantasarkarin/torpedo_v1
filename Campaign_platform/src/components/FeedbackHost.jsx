import { useEffect, useRef, useState } from "react"
import ConfirmDialog from "./ui/ConfirmDialog"

// Renders the toasts and confirm dialogs requested through utils/notify.js.
const STYLE = {
  success: "border-l-4 border-l-cogentix-green",
  error: "border-l-4 border-l-red-600",
  warning: "border-l-4 border-l-cogentix-orange",
  info: "border-l-4 border-l-cogentix-navy",
}
const DANGER = /\b(delete|remove|reject|cancel|discard|stop|clear|reset|disconnect|unlink|archive|purge)\b/i

export default function FeedbackHost() {
  const [toasts, setToasts] = useState([])
  const [ask, setAsk] = useState(null)
  const seq = useRef(0)

  useEffect(() => {
    window.__cxFeedbackHost = true
    const onToast = (e) => {
      const id = ++seq.current
      setToasts((t) => [...t.slice(-3), { id, ...e.detail }])
      const ms = e.detail.type === "error" ? 8000 : 4500
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ms)
    }
    const onConfirm = (e) => setAsk(e.detail)
    window.addEventListener("cx-toast", onToast)
    window.addEventListener("cx-confirm", onConfirm)
    return () => {
      window.__cxFeedbackHost = false
      window.removeEventListener("cx-toast", onToast)
      window.removeEventListener("cx-confirm", onConfirm)
    }
  }, [])

  const answer = (yes) => {
    ask?.resolve(yes)
    setAsk(null)
  }

  return (
    <>
      <div className="fixed right-4 top-20 z-[10000] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id}
               className={`rounded-lg bg-white px-4 py-3 text-sm text-cogentix-navy shadow-card-hover ${STYLE[t.type] || STYLE.info}`}>
            <div className="flex items-start justify-between gap-3">
              <span className="whitespace-pre-line">{t.message}</span>
              <button type="button" aria-label="Dismiss"
                      onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
                      className="cursor-pointer border-0 bg-transparent p-0 text-base leading-none text-cogentix-navy-500">×</button>
            </div>
          </div>
        ))}
      </div>
      {ask && (
        <ConfirmDialog
          isOpen
          onClose={() => answer(false)}
          onConfirm={() => answer(true)}
          title={ask.title || "Please confirm"}
          message={ask.message}
          confirmText={ask.confirmText || "Yes, continue"}
          cancelText={ask.cancelText || "Cancel"}
          variant={ask.variant || (DANGER.test(ask.message) ? "danger" : "info")}
        />
      )}
    </>
  )
}
