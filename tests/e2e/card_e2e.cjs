// End-to-end test of the Lovelace card against a running Home Assistant.
// Not part of CI (needs a live HA). Usage:
//   HA_URL=http://localhost:8123 HA_TOKENS=/tmp/tok.json HA_DASHBOARD=freezer-test/freezer \
//   SHOTS=/tmp/shots node tests/e2e/card_e2e.cjs
// HA_TOKENS is the JSON returned by /auth/token (access_token, refresh_token, expires_in).
// The dashboard view must contain `type: custom:freezer-inventory-card` and the inventory
// should start empty.
const { chromium } = require("playwright");
const fs = require("fs");
const assert = require("assert/strict");

const B = process.env.HA_URL || "http://localhost:8123";
const VIEW = process.env.HA_DASHBOARD || "freezer-test/freezer";
const SHOTS = process.env.SHOTS;
const tok = JSON.parse(fs.readFileSync(process.env.HA_TOKENS || "/tmp/tok.json"));

let step = 0;
async function shot(page, name) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${String(++step).padStart(2, "0")}-${name}.png` });
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 412, height: 900 }, locale: "it-IT" });
  const page = await ctx.newPage();
  const hassTokens = { ...tok, hassUrl: B, clientId: B + "/", expires: Date.now() + tok.expires_in * 1000 };
  await page.addInitScript((t) => localStorage.setItem("hassTokens", t), JSON.stringify(hassTokens));
  page.on("pageerror", (e) => console.log("pageerror:", e.message));

  await page.goto(`${B}/${VIEW}`, { waitUntil: "networkidle" });
  const card = page.locator("freezer-inventory-card");
  await card.locator(".title").waitFor();
  const rows = card.locator(".row");
  const row = (name) => rows.filter({ hasText: name });
  const meta = async (name) => (await row(name).locator(".meta").innerText()).replace(/\s+/g, " ");
  const toast = page.locator("ha-toast, mwc-snackbar, ha-snackbar").first();
  const form = card.locator("dialog.form");
  const take = card.locator("dialog.take");

  // 1. add with weights + note
  await card.locator('button[data-action="add"]').click();
  await form.locator('input[name="name"]').fill("Bistecche di manzo");
  await form.locator('input[name="weights"]').fill("200 300 0,5kg");
  assert.equal(await form.locator('input[name="quantity"]').inputValue(), "3");
  await form.locator('textarea[name="note"]').fill("sottovuoto");
  await shot(page, "add-form");
  await form.locator('button[type="submit"]').click();
  await row("Bistecche").waitFor();
  assert.match(await meta("Bistecche"), /^3 pz · 1 kg · da oggi$/);
  assert.equal(await row("Bistecche").locator(".note").innerText(), "sottovuoto");

  // 2. add with stepper, other category
  await card.locator('button[data-action="add"]').click();
  await form.locator('input[name="name"]').fill("Piselli surgelati");
  await form.locator('[data-cat="verdura"]').click();
  await form.locator('[data-step="1"]').click();
  await form.locator('[data-step="1"]').click();
  await form.locator('button[type="submit"]').click();
  await row("Piselli").waitFor();
  assert.match(await meta("Piselli"), /^3 pz · da oggi$/);

  // 3. validation error stays in the dialog
  await card.locator('button[data-action="add"]').click();
  await form.locator('input[name="name"]').fill("x");
  await form.locator('button[type="submit"]').click();
  await form.locator(".err").filter({ hasText: "tra 2 e 80" }).waitFor();
  await shot(page, "add-error");
  await form.locator('input[name="name"]').fill("Fragole del giardino");
  await form.locator('[data-cat="frutta"]').click();
  await form.locator('button[type="submit"]').click();
  await row("Fragole").waitFor();

  // 4. "+" then undo from the toast
  await row("Piselli").locator('[data-action="plus"]').click();
  await card.locator(".row", { hasText: "Piselli" }).locator(".meta", { hasText: "4 pz" }).waitFor();
  await toast.waitFor({ state: "visible", timeout: 3000 }).catch(() => {});
  await shot(page, "plus-toast");
  const undoInToast = page.getByRole("button", { name: "Annulla" }).last();
  await undoInToast.click();
  await card.locator(".row", { hasText: "Piselli" }).locator(".meta", { hasText: "3 pz" }).waitFor();

  // 5. take a specific piece from the sheet
  await row("Bistecche").locator('[data-action="take"]').click();
  await take.locator(".chip.piece").first().waitFor();
  assert.equal(await take.locator(".chip.piece").count(), 3);
  assert.match(await take.locator(".chip.piece.on").innerText(), /200 g/); // oldest preselected
  await take.locator(".chip.piece", { hasText: "300 g" }).click();
  await shot(page, "take-sheet");
  await take.locator('[data-action="confirm"]').click();
  await card.locator(".row", { hasText: "Bistecche" }).locator(".meta", { hasText: "2 pz · 700 g" }).waitFor();

  // 6. undo from the header button
  await card.locator('button[data-action="undo"]').click();
  await card.locator(".row", { hasText: "Bistecche" }).locator(".meta", { hasText: "3 pz · 1 kg" }).waitFor();

  // 7. edit: fix a weight, backdate a piece, add a piece
  await row("Bistecche").locator(".name").click();
  const prow = form.locator(".piece-row");
  assert.equal(await prow.count(), 3);
  await prow.nth(0).locator(".w").fill("250");
  await prow.nth(1).locator(".d").fill("2026-03-01");
  await form.locator('[data-action="add-piece"]').click();
  await prow.nth(3).locator(".w").fill("400");
  await shot(page, "edit-form");
  await form.locator('button[type="submit"]').click();
  await card.locator(".row", { hasText: "Bistecche" }).locator(".meta", { hasText: "4 pz · 1,45 kg" }).waitFor();
  assert.match(await meta("Bistecche"), /da 8 mesi$/);
  assert.equal(await row("Bistecche").locator(".age.old").count(), 1); // carne > 6 months
  // backdated piece is now the oldest → preselected in the sheet
  await row("Bistecche").locator('[data-action="take"]').click();
  assert.match(await take.locator(".chip.piece.on").innerText(), /300 g\s*01\/03/);
  await take.locator('[data-action="cancel"]').click();

  // 8. sort / filter / search
  await card.locator('[data-sort="category"]').click();
  assert.deepEqual(await card.locator(".group").allInnerTexts(), ["🥩 Carne", "🥦 Verdura", "🍓 Frutta"]);
  await shot(page, "sort-category");
  await card.locator('[data-sort="name"]').click();
  assert.deepEqual(await card.locator(".row .name").allInnerTexts(), ["Bistecche di manzo", "Fragole del giardino", "Piselli surgelati"]);
  await card.locator('[data-filter="verdura"]').click();
  assert.deepEqual(await card.locator(".row .name").allInnerTexts(), ["Piselli surgelati"]);
  await card.locator('[data-filter="all"]').click();
  await card.locator(".search").fill("vuoto"); // matches the note
  assert.deepEqual(await card.locator(".row .name").allInnerTexts(), ["Bistecche di manzo"]);
  await card.locator(".search").fill("");
  await card.locator('[data-sort="date"]').click();
  assert.equal(await card.locator(".row .name").first().innerText(), "Bistecche di manzo"); // oldest piece first

  // 9. last piece → item removed
  await row("Fragole").locator('[data-action="take"]').click();
  assert.equal(await take.locator('[data-action="confirm"]').innerText(), "Preleva ed elimina voce");
  await take.locator('[data-action="confirm"]').click();
  await row("Fragole").waitFor({ state: "detached" });

  // 10. delete needs two taps
  await row("Piselli").locator(".name").click();
  await form.locator('[data-action="delete"]').click();
  assert.equal(await form.locator('[data-action="delete"]').innerText(), "Confermi l'eliminazione?");
  await form.locator('[data-action="delete"]').click();
  await row("Piselli").waitFor({ state: "detached" });

  // 11. sort preference survives a reload
  await card.locator('[data-sort="name"]').click();
  await page.reload({ waitUntil: "networkidle" });
  await card.locator(".row").first().waitFor();
  assert.equal(await card.locator('[data-sort="name"]').getAttribute("class"), "chip on");
  await shot(page, "final");

  console.log("E2E OK");
  await browser.close();
})().catch((err) => {
  console.error("E2E FAILED:", err);
  process.exit(1);
});
