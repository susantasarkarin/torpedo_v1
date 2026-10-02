import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Load a long list in batches (owner, 2026-10-02: "fetch it in batches of 100
 * so that it seeps by the process"). The first batch is shown as soon as it
 * arrives; the rest stream in behind it, 100 at a time, while the page is
 * already usable. Leaving the page or changing `deps` stops the stream.
 *
 *   const { items, loading, loadingMore, total, error, reload } = useBatchedList(
 *     ({ offset, limit, page }) => fetchSomething(offset, limit),  // -> { items, total? } or an array
 *     [filterA, filterB],
 *   )
 *
 * `loading` is true only until the first batch is on screen; `loadingMore`
 * while the rest are still arriving.
 */
export const BATCH_SIZE = 100
const MAX_ITEMS = 50000 // a safety stop, far above any list here

export function useBatchedList(fetchBatch, deps = [], { batchSize = BATCH_SIZE, enabled = true } = {}) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(enabled)
  const [loadingMore, setLoadingMore] = useState(false)
  const [total, setTotal] = useState(null)
  const [error, setError] = useState(null)
  const [nonce, setNonce] = useState(0)
  const run = useRef(0)
  const fetchRef = useRef(fetchBatch)
  fetchRef.current = fetchBatch

  useEffect(() => {
    if (!enabled) return undefined
    const id = ++run.current
    const alive = () => run.current === id
    setItems([])
    setTotal(null)
    setError(null)
    setLoading(true)
    setLoadingMore(false)
    ;(async () => {
      let offset = 0
      let page = 1
      let first = true
      try {
        for (;;) {
          const res = await fetchRef.current({ offset, limit: batchSize, page })
          if (!alive()) return
          const batch = Array.isArray(res) ? res : res?.items || []
          const knownTotal = Array.isArray(res) ? null : res?.total ?? null
          if (knownTotal !== null) setTotal(knownTotal)
          setItems((prev) => (first ? batch : prev.concat(batch)))
          if (first) {
            first = false
            setLoading(false)
            setLoadingMore(true)
          }
          offset += batch.length
          page += 1
          const done = batch.length < batchSize || (knownTotal !== null && offset >= knownTotal) || offset >= MAX_ITEMS
          if (done) break
        }
      } catch (e) {
        if (alive()) setError(e?.message || String(e))
      } finally {
        if (alive()) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    })()
    return () => {
      run.current += 1 // stop this stream
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled, batchSize])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { items, setItems, loading, loadingMore, total, error, reload }
}

/** "Loaded 300 of 2,114…" while the rest of a list is still arriving. */
export function batchProgressText(loaded, total, loadingMore) {
  if (!loadingMore) return ""
  return total ? `Loaded ${loaded.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")}…`
               : `Loaded ${loaded.toLocaleString("en-IN")}… loading more`
}

/**
 * The same batching for pages that keep the list in their own state:
 *
 *   const run = ++loadRun.current
 *   await streamBatches(
 *     ({ offset, limit }) => api.get("/x", { skip: offset, limit }),
 *     (batch, { first, total }) => setRows((prev) => (first ? batch : prev.concat(batch))),
 *     () => loadRun.current === run,   // stop when a newer load started or the page closed
 *   )
 *
 * Resolves after the first batch has been handed over (so callers can clear
 * their spinner); the rest keep arriving through onBatch. `onDone` fires when
 * everything is in.
 */
export function streamBatches(fetchBatch, onBatch, isAlive = () => true,
                              { batchSize = BATCH_SIZE, onDone, onError, maxItems = MAX_ITEMS } = {}) {
  return new Promise((resolveFirst, rejectFirst) => {
    let firstDone = false
    ;(async () => {
      let offset = 0
      let page = 1
      try {
        for (;;) {
          const res = await fetchBatch({ offset, limit: batchSize, page })
          if (!isAlive()) break
          const batch = Array.isArray(res) ? res : res?.items || []
          const total = Array.isArray(res) ? null : res?.total ?? null
          onBatch(batch, { first: !firstDone, total, loaded: offset + batch.length })
          if (!firstDone) {
            firstDone = true
            resolveFirst()
          }
          offset += batch.length
          page += 1
          if (batch.length < batchSize || (total !== null && offset >= total) || offset >= maxItems) break
        }
        if (!firstDone) {
          firstDone = true
          resolveFirst()
        }
        if (isAlive()) onDone?.()
      } catch (e) {
        if (!firstDone) {
          firstDone = true
          rejectFirst(e)
        } else if (isAlive()) {
          onError?.(e)
        }
      }
    })()
  })
}
