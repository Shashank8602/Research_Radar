// Run: node --test worker/test/handler.test.mjs   (no network; Supabase calls are faked)
import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker from "../src/index.js";

const SECRET = "test-secret";
const env = { FEEDBACK_SIGNING_SECRET: SECRET, SUPABASE_URL: "https://db.test", SUPABASE_KEY: "k" };
const b64 = (b) => Buffer.from(b).toString("base64url");

function token(action = "up", exp = Math.floor(Date.now() / 1000) + 3600) {
  const payload = b64(JSON.stringify({ n: "nonce1", i: "item1", r: "run1", a: action, e: exp }));
  return `${payload}.${b64(createHmac("sha256", SECRET).update(payload).digest())}`;
}

function fakeDb({ status = "ok", record = "ok" } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const fn = url.split("/rpc/")[1];
    calls.push(fn);
    const body = fn === "feedback_token_info" ? { status, headline: "A headline" } : record;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return calls;
}

const get = (t, headers = {}) => worker.fetch(new Request(`https://w.test/f/${t}`, { headers }), env);
const NAV = { "sec-fetch-mode": "navigate" };

test("browser click records at once and shows the action message", async () => {
  const calls = fakeDb();
  const res = await get(token("up"), NAV);
  const html = await res.text();
  assert.deepEqual(calls, ["feedback_token_info", "record_feedback"]);
  assert.match(html, /see more items like this/);
  assert.match(html, /class="tick"/);            // the tick mark
  assert.match(html, /window\.close\(\)/);        // closes itself...
  assert.match(html, /,\s*2500\)/);               // ...after 2.5 seconds
  assert.match(html, /id="hint"[^>]*>You can close this tab/);  // fallback hint, hidden until needed
  assert.doesNotMatch(html, /<form/);
  assert.doesNotMatch(html, /A headline/);       // just a tick and a message
});

test("each action has its own message", async () => {
  fakeDb();
  assert.match(await (await get(token("down"), NAV)).text(), /fewer items/);
  assert.match(await (await get(token("save"), NAV)).text(), /reading list/);
});

test("scanner or prefetch (no navigate header) writes nothing and shows the confirm button", async () => {
  for (const headers of [{}, { "sec-fetch-mode": "no-cors" }, { ...NAV, "sec-purpose": "prefetch" }]) {
    const calls = fakeDb();
    const html = await (await get(token("up"), headers)).text();
    assert.deepEqual(calls, ["feedback_token_info"], JSON.stringify(headers));
    assert.match(html, /<form method="POST">/);
  }
});

test("HEAD never writes", async () => {
  const calls = fakeDb();
  await worker.fetch(new Request(`https://w.test/f/${token()}`, { method: "HEAD", headers: NAV }), env);
  assert.ok(!calls.includes("record_feedback"));
});

test("a used link says already recorded, with the same message", async () => {
  fakeDb({ status: "used" });
  const html = await (await get(token("up"), NAV)).text();
  assert.match(html, /Already recorded\. .*more items like this/);
  assert.match(html, /class="tick"/);
});

test("bad signature, expired token and failing database are handled", async () => {
  fakeDb();
  assert.equal((await get(token("up") + "x", NAV)).status, 400);
  assert.equal((await get(token("up", 1), NAV)).status, 410);
  globalThis.fetch = async () => new Response("boom", { status: 500 });
  assert.equal((await get(token("up"), NAV)).status, 502);
});

test("POST from the confirm button still records", async () => {
  const calls = fakeDb();
  const res = await worker.fetch(new Request(`https://w.test/f/${token("up")}`, { method: "POST" }), env);
  assert.deepEqual(calls, ["record_feedback"]);
  assert.match(await res.text(), /more items like this/);
});
