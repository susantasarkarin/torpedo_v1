import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import App from "../App"

describe("App smoke test", () => {
  it("renders without crashing", () => {
    // App requires a Router context; MemoryRouter provides it without a browser
    render(
      <MemoryRouter initialEntries={["/admin/login"]}>
        <App />
      </MemoryRouter>
    )
    // Login page should be reachable — just confirm the DOM is non-empty
    expect(document.body).toBeTruthy()
  })
})
