import { render, screen, within } from "@testing-library/react"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { authFetch } from "../../../utils/api"
import RewardsPoints from "../RewardsPoints"

vi.mock("../../../utils/api", () => ({ authFetch: vi.fn() }))

const redemption = (id, name, extra = {}) => ({
  id, name, email: `${id}@example.com`, panelistId: `SFW${id}`, country: "IN", at: "2026-11-20T10:00:00Z",
  points: 1000, giftCard: "₹100", fulfilledAt: null, fulfilledBy: "", onHold: false, holdReasons: [], suspended: false, ...extra,
})

const respond = (body) => authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => body })

describe("RewardsPoints", { timeout: 20000 }, () => {
  beforeEach(() => { authFetch.mockReset() })

  it("lists everyone who asked to redeem, with no summary boxes, tabs or points-by-reason", async () => {
    respond({
      totals: { toSend: 1, onHold: 1, earnedPoints: 79948, onHoldPoints: 0, redeemedPoints: 3500, balancePoints: 76464 },
      byType: [{ label: "Quick start", awards: 1325, earnedPoints: 40100, onHoldPoints: 0 }],
      redemptions: [
        redemption("a1", "Asha Rao"),
        redemption("b2", "Ben Ola", { onHold: true, holdReasons: ["Profile quality flags: QC_04"] }),
        redemption("c3", "Chen Li", { fulfilledAt: "2026-11-21T09:00:00Z", fulfilledBy: "admin" }),
      ],
    })
    render(<RewardsPoints embedded />)
    expect(await screen.findByText("Asha Rao")).toBeInTheDocument()
    expect(screen.getByText("Ben Ola")).toBeInTheDocument()
    expect(screen.getByText("Chen Li")).toBeInTheDocument()
    expect(screen.getByText("a1@example.com")).toBeInTheDocument()
    expect(screen.getByText(/Point redemption requests/)).toHaveTextContent("· 3")
    const headers = [...document.querySelectorAll("thead th")].map((h) => h.textContent)
    expect(headers).toEqual(["Name", "Email", "Country", "Requested", "Points", "Gift card", "Status"])
    // Actions still there: send / hold for open requests, release for held ones.
    const row = (name) => screen.getByText(name).closest("tr")
    expect(within(row("Asha Rao")).getByText("Mark sent")).toBeInTheDocument()
    expect(within(row("Ben Ola")).getByText("Release")).toBeInTheDocument()
    expect(within(row("Chen Li")).getByText(/^Sent /)).toBeInTheDocument()
    // Removed: summary boxes, status tabs, points by reason.
    for (const gone of ["Gift cards to send", "Points in balances", "Points by reason", "To send", "All"]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument()
    }
  })

  it("says so when nobody has redeemed", async () => {
    respond({ totals: {}, byType: [], redemptions: [] })
    render(<RewardsPoints embedded />)
    expect(await screen.findByText("No one has asked to redeem their points yet.")).toBeInTheDocument()
  })
})
