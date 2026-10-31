// Regression test for "Custom element not found: freezer-inventory-card".
// The HA frontend swaps window.customElements for a scoped-registry polyfill
// after extra modules start loading. The card must register on the registry
// that is current when <home-assistant> gets defined, not at module load.
// Run: node --test tests/frontend/card_registration.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

class FakeRegistry {
  constructor(name) { this.name = name; this.defs = new Map(); this.waiters = new Map(); }
  get(tag) { return this.defs.get(tag); }
  define(tag, cls) {
    if (this.defs.has(tag)) throw new Error(`${this.name}: ${tag} already defined`);
    this.defs.set(tag, cls);
    (this.waiters.get(tag) || []).forEach((r) => r(cls));
  }
  whenDefined(tag) {
    if (this.defs.has(tag)) return Promise.resolve(this.defs.get(tag));
    return new Promise((r) => this.waiters.set(tag, [...(this.waiters.get(tag) || []), r]));
  }
}

test("card registers on the registry installed by the HA frontend", async () => {
  const native = new FakeRegistry("native");
  globalThis.HTMLElement = class {};
  globalThis.window = globalThis;
  globalThis.customElements = native;

  const card = pathToFileURL(resolve("custom_components/freezer_inventory/frontend/freezer-inventory-card.js"));
  await import(card.href);
  assert.equal(native.get("freezer-inventory-card"), undefined, "must not register at module load");

  // frontend boots: polyfill replaces the global, then defines <home-assistant>
  // (the polyfill forwards definitions to the native registry)
  const polyfill = new FakeRegistry("polyfill");
  globalThis.customElements = polyfill;
  native.define("home-assistant", class {});
  polyfill.define("home-assistant", class {});
  await new Promise((r) => setTimeout(r, 0));

  assert.ok(polyfill.get("freezer-inventory-card"), "visible to Lovelace");
  assert.equal(window.customCards.filter((c) => c.type === "freezer-inventory-card").length, 1);
});
