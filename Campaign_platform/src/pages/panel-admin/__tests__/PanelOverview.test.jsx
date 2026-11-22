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
    members: 495, joinedLast30d: 88, activeLast30d: 123, activeLast30dPct: 24.8, completedLast30d: 31,
    attemptsLast30d: 1240, completeAttemptsLast30d: 62, attemptConversionLast30d: 5,
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
    { code: "", name: "Unknown", members: 40, quickDone: 14, completed: 2 },
    { code: "MG", name: "Madagascar", members: 3, quickDone: 1, completed: 0 },
    { code: "NG", name: "Nigeria", members: 2, quickDone: 1, completed: 0 },
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

  it("has plain journey rows: no expand arrows, details or action buttons", async () => {
    await renderPage()
    expect(document.querySelectorAll("[aria-expanded]")).toHaveLength(0)
    expect(document.querySelectorAll("tr[data-detail]")).toHaveLength(0)
    expect(screen.queryByText(/[▸▾]/)).not.toBeInTheDocument()
    expect(screen.queryByText("Review survey matching")).not.toBeInTheDocument()
    expect(screen.queryByText("#1")).not.toBeInTheDocument()
  })

  it("shows the five KPI cards, with attempts and conversion", async () => {
    await renderPage()
    for (const label of ["Total panel members", "New signups in the past 30 days", "Active in the last 30 days", "Survey attempts in the last 30 days", "Completed a survey in the last 30 days"]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText("88")).toBeInTheDocument()
    expect(screen.getByText("123")).toBeInTheDocument()
    expect(screen.getByText("24.8% of members")).toBeInTheDocument()
    expect(screen.getByText("31")).toBeInTheDocument()
    expect(screen.getByText("1,240")).toBeInTheDocument()
    expect(screen.getByText("Conversion 5% (62 of 1,240 attempts completed)")).toBeInTheDocument()
    expect(screen.queryByText("Points owed")).not.toBeInTheDocument()
    expect(screen.queryByText(/this week/)).not.toBeInTheDocument()
  })

  it("has exactly the four journey columns and computes drop off", async () => {
    await renderPage()
    const table = stageRow("signup").closest("table")
    expect([...table.querySelectorAll("thead th")].map((h) => h.textContent)).toEqual(["Stage", "Members reached", "Conversion", "Drop off (%)"])
    expect(stageRow("membership").querySelector('[data-col="dropoff"]').textContent).toBe("31.6%") // 132 / 418
    expect(stageRow("signup").querySelector('[data-col="dropoff"]').textContent).toBe("11.3%")    // 56 / 495
    expect(stageRow("repeat").querySelector('[data-col="dropoff"]').textContent).toBe("60.0%")    // 6 / 10
    expect(stageRow("redeemed").querySelector('[data-col="dropoff"]').textContent).toBe("—")
  })

  it("gives the Redeemed row no conversion %", async () => {
    await renderPage()
    const row = stageRow("redeemed")
    expect(within(row).getByText("Redeemed points")).toBeInTheDocument()
    expect(row.querySelector('[data-col="conversion"]').textContent).toBe("—")
    expect(row.textContent).not.toMatch(/%/)
  })

  it("lists every country by panelists, Unknown last, with only two columns", async () => {
    await renderPage()
    const rows = [...document.querySelectorAll("tbody tr[data-country]")]
    expect(rows.map((r) => r.getAttribute("data-country"))).toEqual(["IN", "GB", "US", "MG", "NG", "unknown"])
    const table = rows[0].closest("table")
    expect([...table.querySelectorAll("thead th")].map((h) => h.textContent)).toEqual(["Country", "Panelists"])
    expect(screen.queryByText("Other")).not.toBeInTheDocument()
    const totalRow = document.querySelector('tr[data-country="total"]')
    expect(within(totalRow).getByText("495")).toBeInTheDocument()
  })

  it("has no alerts / data issues bar, even when there are issues and alerts", async () => {
    await renderPage(fixture({
      dataIssues: [{ id: "unmapped_outcomes", title: "Unmapped outcomes", detail: "2 statuses", severity: "medium" }],
      alerts: { securityTermsToday: 2, securityTermsWeek: 5, flaggedProfiles: 9 },
    }))
    expect(screen.queryByText(/data issue/)).not.toBeInTheDocument()
    expect(screen.queryByText(/security termination/)).not.toBeInTheDocument()
    expect(screen.queryByText(/quality review/)).not.toBeInTheDocument()
  })

  it("re-fetches with filters", async () => {
    await renderPage()
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
