import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listProjects,
  createProject,
  setProjectFavorite,
  downloadTrafficReport,
  createCleaningRequest,
  getSurveyTrend,
  updateCleaningRequestStatus,
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

  it("posts a cleaning request with its survey ids and notes", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "r1", status: "submitted" }));

    await createCleaningRequest("P1", { surveyIds: ["S1", "S2"], notes: "Drop speeders" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/ops/projects/P1/cleaning-requests");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ surveyIds: ["S1", "S2"], notes: "Drop speeders" });
  });

  it("sends the survey trend window as the days query parameter", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ days: [], series: [], total: { entrants: [], completes: [] } }));

    await getSurveyTrend("S9", 30);

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/ops/surveys/S9/trend?");
    expect(url).toContain("days=30");
  });

  it("posts a cleaning status change with its note", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "r1", status: "in_progress" }));

    await updateCleaningRequestStatus("r1", { status: "in_progress", note: "Picked up" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/ops/cleaning-requests/r1/status");
    expect(JSON.parse(init.body)).toEqual({ status: "in_progress", note: "Picked up" });
  });

  it("turns a 422 validation array into a readable message and per-field errors", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "surveyUrl"], msg: "field required" },
            { loc: ["body", "ir"], msg: "must be ≤ 100" },
          ],
        },
        422
      )
    );

    const err = await createProject({ projectName: "A" }).catch((e) => e);

    expect(err).toBeInstanceOf(OpsApiError);
    expect(err.status).toBe(422);
    expect(err.message).toBe("surveyUrl: field required; ir: must be ≤ 100");
    expect(err.fieldErrors).toEqual({ surveyUrl: "field required", ir: "must be ≤ 100" });
    expect(Array.isArray(err.detail)).toBe(true);
  });

  it("keeps a string detail as the message with no field errors", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "No survey URL set" }, 404));

    const err = await createProject({}).catch((e) => e);

    expect(err.message).toBe("No survey URL set");
    expect(err.fieldErrors).toEqual({});
  });

  it("reports a network failure as an OpsApiError with status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const err = await listProjects({}).catch((e) => e);

    expect(err).toBeInstanceOf(OpsApiError);
    expect(err.status).toBe(0);
  });
});
