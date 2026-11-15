import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listProjects,
  createProject,
  setProjectFavorite,
  downloadTrafficReport,
  OpsApiError,
} from "../services/opsProjectsService";

const jsonResponse = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("opsProjectsService", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds the list query and drops empty parameters", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, counts: {} }));

    await listProjects({ status: "live", q: "", sort: "projectName", order: "asc", page: 2, pageSize: 20 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/ops/projects?");
    expect(url).toContain("status=live");
    expect(url).toContain("page=2");
    expect(url).toContain("pageSize=20");
    expect(url).not.toContain("q=");
  });

  it("maps a 409 on create to an OpsApiError with status and server message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Project number already exists" }, 409));

    const err = await createProject({ projectName: "A", projectNumber: "P-1" }).catch((e) => e);

    expect(err).toBeInstanceOf(OpsApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("Project number already exists");
  });

  it("sends the favourite toggle as a JSON POST body", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "p1", isFavorite: true }));

    await setProjectFavorite("p1", true);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/ops/projects/p1/favorite");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ isFavorite: true });
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("returns the traffic report blob with the filename from Content-Disposition", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("respondent,status\n1,complete\n", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="traffic-S1.csv"' },
      })
    );

    const { blob, filename } = await downloadTrafficReport("S1", { format: "csv" });

    expect(filename).toBe("traffic-S1.csv");
    expect(blob.size).toBeGreaterThan(0);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/ops/surveys/S1/traffic-report?format=csv");
  });

  it("reports a network failure as an OpsApiError with status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const err = await listProjects({}).catch((e) => e);

    expect(err).toBeInstanceOf(OpsApiError);
    expect(err.status).toBe(0);
  });
});
