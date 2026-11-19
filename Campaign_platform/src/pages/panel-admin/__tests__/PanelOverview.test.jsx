import { render, screen, within, fireEvent, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { authFetch } from "../../../utils/api"
import PanelOverview from "../PanelOverview"

vi.mock("../../../utils/api", () => ({ authFetch: vi.fn() }))

const members = (completed, skipped = 0) => ({
  kind: "members",
  items: [{ key: "completed", label: "Completed", count: completed }, ...(skipped ? [{ key: "skipped", label: "Skipped (legacy)", count: skipped }] : [])],
})
const stage = (key, label, reached, skipped, stoppedHere, prevReached, extra = {}) => ({
  key, label, reached, skipped, completed: reached - skipped,
  pctOfSignups: Math.round((reached / 495) * 1000) / 10,
  pctOfPrevious: prevReached ? Math.round((reached / prevReached) * 1000) / 10 : 100,
  stoppedHere,
  stoppedByLastSeen: { today: 0, last7d: Math.floor(stoppedHere / 4), quiet: stoppedHere - Math.floor(stoppedHere / 4) },
  missing: `missing-${key}`, nextStep: `next-${key}`, action: null,
  breakdown: members(reached - skipped, skipped),
  ...extra,
})

const fixture = (overrides = {}) => ({
  generatedAt: "2026-11-19T10:30:00.000Z",
  filters: { country: "", days: 0 },
  total: 495,
  kpis: {
    members: 495, joinedThisWeek: 7, activeLast7d: 65, activeLast7dPct: 13.1, completed: 57, repeat: 10,
    pointsOwed: { points: 75000, ledgerPoints: 75000, matches: true, membersWithBalance: 40 },
  },
  stages: [
    stage("signup", "Signed up", 495, 0, 56, 0, { action: { label: "Check signup source", stage: "signup" } }),
    stage("verified", "Email verified", 439, 0, 21, 495),
    stage("membership", "Membership confirmed", 418, 230, 132, 439, { action: { label: "Send Quick start reminder", stage: "membership" } }),
    stage("quickDone", "Quick start done", 286, 120, 16, 418),
    stage("clicked", "Clicked a survey", 270, 0, 36, 286, {
      action: { label: "Review survey matching", stage: "clicked" },
      breakdown: { kind: "attempts", items: [{ key: "drop_off", label: "Dropped off", count: 40 }, { key: "blocked", label: "Blocked", count: 9 }] },
    }),
    stage("result", "Got a survey result", 234, 0, 177, 270, {
      action: { label: "Review survey matching", stage: "result" },
      breakdown: { kind: "attempts", items: [{ key: "screened_out", label: "Screened out", count: 1500 }, { key: "quota_full", label: "Survey full", count: 9 }] },
    }),
    stage("completed", "Completed a survey", 57, 0, 47, 234, { action: { label: "Invite active members", stage: "completed" } }),
    stage("repeat", "2+ completes", 10, 1, 6, 57, { nextStep: "—" }),
  ],
  redeemed: 4,
  countries: [
    { code: "IN", name: "India", members: 300, quickDone: 200, completed: 40 },
    { code: "GB", name: "United Kingdom", members: 120, quickDone: 50, completed: 10 },
    { code: "US", name: "United States", members: 30, quickDone: 20, completed: 5 },
    { code: "MG", name: "Madagascar", members: 3, quickDone: 1, completed: 0 },
    { code: "NG", name: "Nigeria", members: 2, quickDone: 1, completed: 0 },
    { code: "", name: "Unknown", members: 40, quickDone: 14, completed: 2 },
  ],
  invariants: { stoppedTotal: 491, redeemed: 4, total: 495, ok: true, stageAgeOk: true, countriesOk: true },
  dataIssues: [],
  alerts: { securityTermsToday: 0, securityTermsWeek: 3, flaggedProfiles: 2 },
  ...overrides,
})

const respond = (body) => authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => body })

const renderPage = async (body = fixture()) => {
  respond(body)
  render(<MemoryRouter><PanelOverview /></MemoryRouter>)
  await screen.findByText("Member journey")
}

const stageRow = (key) => document.querySelector(`tr[data-stage="${key}"]`)
// Role queries are slow on this table in jsdom; the label text sits inside the toggle button.
const stageButton = (label) => screen.getByText(label, { selector: "button *, button" }).closest("button")

describe("PanelOverview", { timeout: 20000 }, () => {
  beforeEach(() => { authFetch.mockReset() })

  it("is one page with no tabs, from one request", async () => {
    await renderPage()
    expect(screen.queryByText("Summary")).not.toBeInTheDocument()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(authFetch).toHaveBeenCalledTimes(1)
    expect(authFetch.mock.calls[0][0]).toContain("/api/panel-admin/member-funnel")
  })

  it("shows the footer that adds up to the total", async () => {
    await renderPage()
    expect(screen.getByText("491 stopped along the way + 4 redeemed = 495")).toBeInTheDocument()
  })

  it("tags the result stage #1 and opens it by default", async () => {
    await renderPage()
    const row = stageRow("result")
    expect(within(row).getByText("#1")).toBeInTheDocument()
    expect(within(stageRow("membership")).getByText("#2")).toBeInTheDocument()
    expect(within(stageRow("signup")).getByText("#3")).toBeInTheDocument()
    expect(stageButton("Got a survey result")).toHaveAttribute("aria-expanded", "true")
    expect(document.querySelectorAll("tr[data-detail]")).toHaveLength(1)
    expect(screen.getByText("Survey attempts by outcome")).toBeInTheDocument()
    expect(screen.getByText(/not members/)).toBeInTheDocument()
  })

  it("keeps only one expanded row at a time", async () => {
    await renderPage()
    fireEvent.click(stageButton("Quick start done"))
    const details = document.querySelectorAll("tr[data-detail]")
    expect(details).toHaveLength(1)
    expect(details[0].getAttribute("data-detail")).toBe("quickDone")
    expect(stageButton("Got a survey result")).toHaveAttribute("aria-expanded", "false")
    expect(stageButton("Quick start done")).toHaveAttribute("aria-expanded", "true")
  })

  it("shows Quick start completed 166 vs skipped 120", async () => {
    await renderPage()
    fireEvent.click(stageButton("Quick start done"))
    const detail = document.querySelector('tr[data-detail="quickDone"]')
    expect(within(detail).getByText(/Completed 166 · Skipped \(legacy\) 120/)).toBeInTheDocument()
  })

  it("gives the Redeemed row no conversion %", async () => {
    await renderPage()
    const row = stageRow("redeemed")
    expect(within(row).getByText("Redeemed points")).toBeInTheDocument()
    expect(row.querySelector('[data-col="conversion"]').textContent).toBe("—")
    expect(row.textContent).not.toMatch(/%/)
  })

  it("pins Unknown last and groups countries under 5 members as Other", async () => {
    await renderPage()
    const rows = [...document.querySelectorAll("tbody tr[data-country]")]
    expect(rows.map((r) => r.getAttribute("data-country"))).toEqual(["IN", "GB", "US", "other", "unknown"])
    const other = rows[3]
    expect(other.textContent).toContain("Other")
    expect(other.textContent).toContain("Madagascar, Nigeria")
    expect(within(other).getByText("5")).toBeInTheDocument()
    expect(rows[4].textContent).toContain("no country captured")
    const totalRow = document.querySelector('tr[data-country="total"]')
    expect(within(totalRow).getByText("495")).toBeInTheDocument()
  })

  it("hides the data issues button when there are none", async () => {
    await renderPage()
    expect(screen.queryByText(/data issue/)).not.toBeInTheDocument()
  })

  it("expands data issues when present", async () => {
    await renderPage(fixture({ dataIssues: [{ id: "unmapped_outcomes", title: "Unmapped outcomes", detail: "2 statuses", severity: "medium" }] }))
    const btn = screen.getByText(/1 data issue/).closest("button")
    expect(btn).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(btn)
    expect(btn).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("Unmapped outcomes")).toBeInTheDocument()
  })

  it("hides zero alerts and re-fetches with filters", async () => {
    await renderPage()
    expect(screen.getByText(/2 profiles waiting for quality review/)).toBeInTheDocument()
    expect(screen.queryByText(/security termination/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Members"), { target: { value: "30" } })
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2))
    expect(authFetch.mock.calls[1][0]).toContain("days=30")
  })

  it("shows one error box when the fetch fails", async () => {
    authFetch.mockResolvedValue({ ok: false, status: 502, json: async () => ({}) })
    render(<MemoryRouter><PanelOverview /></MemoryRouter>)
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 502")
  })
})
