import { render, screen, within, waitFor, fireEvent } from "@testing-library/react"
import { MemoryRouter, Routes, Route } from "react-router-dom"
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest"
import { authFetch } from "../../../utils/api"
import ProfilingAdmin from "../ProfilingAdmin"

vi.mock("../../../utils/api", () => ({ authFetch: vi.fn() }))

const member = (userId, email, flags, extra = {}) => ({
  userId, email, country: "IN", createdAt: "2026-10-01T10:00:00.000Z", redemptionHeld: false, suspended: false, flags, ...extra,
})
const flag = (rule, label, extra = {}) => ({ rule, label, at: "2026-11-19T09:00:00.000Z", ...extra })

const fixture = () => ({
  members: [
    member("u1", "few@x.test", [flag("QC_04", "Personal income above household income")]),
    member("u2", "many@x.test", [
      flag("QC_02", "Rushed a profile section", { section: "Telecom & digital", count: 3 }),
      flag("QC_08", "Says they have/plan almost everything"),
    ]),
    member("u3", "held@x.test", [flag("QC_06", "No licence but main driver")], { redemptionHeld: true }),
    member("u4", "susp@x.test", [flag("QC_12", "Pasted the interview answer instead of typing")], { suspended: true }),
  ],
})

let data
const respond = (body) => ({ ok: true, status: 200, json: async () => body })
const urls = () => authFetch.mock.calls.map((c) => [c[0], c[1] && c[1].method, c[1] && c[1].body])

const renderPage = async () => {
  render(<MemoryRouter><ProfilingAdmin embedded /></MemoryRouter>)
  await screen.findByText(/Quality flags to review/)
  await screen.findByText("many@x.test")
}
const takeAction = (row) => { fireEvent.click(within(row).getByText("Take action")) }
const emails = () => [...document.querySelectorAll("tr[data-member]")].map((r) => within(r).getAllByRole("link")[0].textContent)

describe("ProfilingAdmin flag review", { timeout: 20000 }, () => {
  beforeEach(() => {
    authFetch.mockReset()
    data = fixture()
    authFetch.mockImplementation(async (url, opts) => (String(url).endsWith("/profiling/flags") || (opts && opts.method === "POST")
      ? respond(data)
      : { ok: false, status: 500, json: async () => ({ detail: "not under test" }) }))
  })
  afterEach(() => { vi.restoreAllMocks() })

  it("shows labels with section, count and date, and the member count", async () => {
    await renderPage()
    expect(screen.getByText("Quality flags to review · 4 members")).toBeInTheDocument()
    expect(screen.getByText("Rushed a profile section — Telecom & digital (×3), 19 Nov")).toBeInTheDocument()
    expect(screen.getByText("Personal income above household income, 19 Nov")).toBeInTheDocument()
    expect(screen.getAllByText("On hold")).toHaveLength(1)
    expect(screen.getByText("Suspended")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "many@x.test" })).toHaveAttribute("href", "/admin/panel-admin/members/u2")
  })

  it("sorts held redemptions first, then by number of flags", async () => {
    await renderPage()
    expect(emails()).toEqual(["held@x.test", "many@x.test", "few@x.test", "susp@x.test"])
  })

  it("filters to members with a held redemption", async () => {
    await renderPage()
    fireEvent.click(screen.getByLabelText("Only members with a held redemption"))
    expect(emails()).toEqual(["held@x.test"])
    expect(screen.getByText("Quality flags to review · 1 members")).toBeInTheDocument()
  })

  it("clears all flags after confirming, then reloads", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
    await renderPage()
    const row = document.querySelector('tr[data-member="u2"]')
    fireEvent.click(within(row).getByText("Clear"))
    expect(confirm).toHaveBeenCalledWith("Clear all 2 flags for many@x.test? Their held redemption will be released if nothing else holds it.")
    await waitFor(() => expect(urls().some(([u, m]) => u.endsWith("/api/panel-admin/profiling/flags/u2/clear-all") && m === "POST")).toBe(true))
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => c[0].endsWith("/profiling/flags")).length).toBe(2))
  })

  it("does nothing when the clear confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false)
    await renderPage()
    fireEvent.click(within(document.querySelector('tr[data-member="u1"]')).getByText("Clear"))
    expect(urls().some(([u]) => u.includes("clear-all"))).toBe(false)
  })

  it("requires a reason to suspend", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("   ")
    await renderPage()
    const row = document.querySelector('tr[data-member="u1"]')
    takeAction(row)
    fireEvent.click(within(row).getByText("Suspend member"))
    expect(prompt).toHaveBeenCalled()
    expect(urls().some(([u]) => u.includes("/suspend"))).toBe(false)
    prompt.mockReturnValue("Fake answers")
    takeAction(row)
    fireEvent.click(within(row).getByText("Suspend member"))
    await waitFor(() => expect(urls().some(([u, m, b]) => u.endsWith("/api/panel-admin/members/u1/suspend") && m === "POST" && JSON.parse(b).reason === "Fake answers")).toBe(true))
  })

  it("offers Unsuspend for suspended members", async () => {
    await renderPage()
    const row = document.querySelector('tr[data-member="u4"]')
    expect(within(row).queryByText("Take action")).not.toBeInTheDocument()
    fireEvent.click(within(row).getByText("Unsuspend"))
    await waitFor(() => expect(urls().some(([u, m]) => u.endsWith("/api/panel-admin/members/u4/unsuspend") && m === "POST")).toBe(true))
  })

  it("shows the empty state", async () => {
    data = { members: [] }
    render(<MemoryRouter><ProfilingAdmin embedded /></MemoryRouter>)
    expect(await screen.findByText("No flags to review.")).toBeInTheDocument()
  })

  it("keeps the existing sections below the table", async () => {
    await renderPage()
    expect(authFetch.mock.calls.some((c) => c[0].includes("/profiling/stats"))).toBe(true)
    expect(authFetch.mock.calls.some((c) => c[0].includes("/profiling/lists"))).toBe(true)
  })

  it("Take action can keep the redemption on hold without calling anything", async () => {
    await renderPage()
    const row = document.querySelector('tr[data-member="u3"]')
    takeAction(row)
    fireEvent.click(within(row).getByText("Keep redemption on hold"))
    expect(within(row).queryByText("Suspend member")).not.toBeInTheDocument()
    expect(urls().some(([, m]) => m === "POST")).toBe(false)
  })

  it("Investigate opens the member page in the same tab", async () => {
    render(<MemoryRouter><Routes><Route path="/" element={<ProfilingAdmin embedded />} /><Route path="/admin/panel-admin/members/:id" element={<div>member page</div>} /></Routes></MemoryRouter>)
    await screen.findByText("many@x.test")
    fireEvent.click(within(document.querySelector('tr[data-member="u2"]')).getByText("Investigate"))
    expect(await screen.findByText("member page")).toBeInTheDocument()
  })
})
