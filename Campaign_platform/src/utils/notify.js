// App-wide feedback instead of the browser's alert() and confirm().
//
//   notify("Saved")                          -> a toast (type guessed from the text)
//   notify("Could not save", "error")
//   if (!(await confirmAction("Delete this vendor?"))) return
//
// Rendered by components/FeedbackHost.jsx, mounted once in App.jsx. If no
// host is mounted (a page outside the app shell), the browser dialogs are
// used so nothing is ever lost silently.

const ERROR_WORDS = /\b(error|fail|failed|failure|could not|couldn't|cannot|can't|unable|invalid|denied|not found|missing)\b/i
const WARNING_WORDS = /\b(please|required|select|choose|enter|warning|must|no .* selected)\b/i

export function guessType(message) {
  const s = String(message ?? "")
  if (/^\s*(❌|⚠️)/.test(s) || ERROR_WORDS.test(s)) return "error"
  if (WARNING_WORDS.test(s)) return "warning"
  return "success"
}

export function notify(message, type) {
  const text = typeof message === "string" ? message : (message?.message ?? JSON.stringify(message))
  if (typeof window === "undefined") return
  if (!window.__cxFeedbackHost) {
    window.alert(text)
    return
  }
  window.dispatchEvent(new CustomEvent("cx-toast", { detail: { message: text, type: type || guessType(text) } }))
}

export function confirmAction(message, options = {}) {
  if (typeof window === "undefined") return Promise.resolve(false)
  if (!window.__cxFeedbackHost) return Promise.resolve(window.confirm(message))
  return new Promise((resolve) => {
    window.dispatchEvent(new CustomEvent("cx-confirm", { detail: { message: String(message), ...options, resolve } }))
  })
}
