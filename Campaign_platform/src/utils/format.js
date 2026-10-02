// One way to show dates across the admin app: "2 Oct 2026", "2 Oct 2026, 14:05".
// Shown in India time.
//
// The backend stores UTC (datetime.utcnow) and sends ISO strings without a
// zone ("2026-10-01T09:30:00"). The browser reads those as LOCAL time, so
// times were shown 5h30 early in India. A zone-less timestamp is read as UTC.

const TZ = "Asia/Kolkata"
const LOCALE = "en-GB" // day month year, 24-hour clock

export function toDate(value) {
  if (value === null || value === undefined || value === "") return null
  if (value instanceof Date) return isNaN(value) ? null : value
  if (typeof value === "object" && value.$date) value = value.$date
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(value)) {
    value += "Z"
  }
  const d = new Date(value)
  return isNaN(d) ? null : d
}

export function formatDate(value, fallback = "—") {
  const d = toDate(value)
  return d ? d.toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric", timeZone: TZ }) : fallback
}

export function formatDateTime(value, fallback = "—") {
  const d = toDate(value)
  return d
    ? d.toLocaleString(LOCALE, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
                                 hour12: false, timeZone: TZ })
    : fallback
}

export function formatTime(value, fallback = "—") {
  const d = toDate(value)
  return d ? d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ }) : fallback
}
