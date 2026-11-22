// JSON body, or a readable message when the server sent an HTML/timeout page
// (Cloudflare 522/524 during long uploads).
export async function parseApiResponse(res) {
  const contentType = (res.headers.get("content-type") || "").toLowerCase()
  if (contentType.includes("application/json")) return await res.json()
  const text = await res.text()
  return {
    detail:
      res.status === 524 || res.status === 522
        ? `Server timeout (HTTP ${res.status}) — the backend took too long to respond.`
        : `Unexpected server response (${res.status}): ${text}`,
  }
}
