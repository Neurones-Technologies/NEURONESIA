import { test, expect, type Cookie } from "@playwright/test";

const SHOTS = ["objectifs", "comptes", "pipe-qualite", "cycle-vie", "marche", "equipe", "visites"];
const DIR = "C:/Users/SOROLA~1/AppData/Local/Temp/claude/d--nt-ai-v/fcead07e-6c31-4cdf-b62a-fcce101685e5/scratchpad/shots";

test.describe("captures", () => {
  let session: Cookie[] = [];
  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = await playwright.request.newContext({ baseURL });
    const r = await api.post("/api/auth/login", {
      data: { email: "pbourron@neuronestech.com", password: "neurones2026" },
    });
    expect(r.ok()).toBeTruthy();
    session = (await api.storageState()).cookies;
    await api.dispose();
  });

  test("capture les onglets DC", async ({ context }) => {
    await context.addCookies(session);
    const page = await context.newPage();
    await page.setViewportSize({ width: 1600, height: 1200 });
    for (const s of SHOTS) {
      await page.goto(`/dc/vision/${s}`);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${DIR}/${s}.png`, fullPage: true });
    }
  });
});
