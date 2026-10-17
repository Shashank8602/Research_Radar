// Research Radar feedback endpoint (Cloudflare Worker).
//
//   GET  /f/<token>  -> from a real browser click (Sec-Fetch-Mode: navigate): records the vote and shows the result.
//                       from anything else (mail scanners, link previews, prefetch): shows a confirm page and
//                       changes NOTHING, so automated pre-fetching can never cast a vote.
//   POST /f/<token>  -> the confirm page's button; verifies the signed token and records the vote.
//
// Token = base64url(JSON{n: nonce, i: item, r: run, a: action, e: expiry-unix}) + "." + base64url(HMAC-SHA256).
// Secrets (wrangler secret put): FEEDBACK_SIGNING_SECRET, SUPABASE_URL, SUPABASE_KEY (publishable key).

const ACTIONS = {
  up: {
    title: "More like this",
    ask: "Show you more items like this one?",
    button: "Yes, more like this",
    done: "Noted. You'll see more items like this.",
  },
  down: {
    title: "Less like this",
    ask: "Show you fewer items like this one?",
    button: "Yes, less like this",
    done: "Noted. You'll see fewer items like this.",
  },
  save: {
    title: "Save for later",
    ask: "Save this item to your reading list?",
    button: "Save it",
    done: "Saved to your reading list.",
  },
  deepdive: {
    title: "Explain in depth",
    ask: "Open a detailed explanation of this item?",
    button: "Open",
    done: "Opening…",
  },
};

const enc = new TextEncoder();

function b64urlToBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function verifyToken(token, secret) {
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [payloadB64, sigB64] = parts;
  try {
    const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("HMAC", key, b64urlToBytes(sigB64), enc.encode(payloadB64));
    if (!ok) return null;
    const p = JSON.parse(new TextDecoder().decode(b64urlToBytes(payloadB64)));
    if (!p.n || !p.i || !p.r || !ACTIONS[p.a] || typeof p.e !== "number") return null;
    if (p.e < Date.now() / 1000) return { expired: true };
    return p;
  } catch {
    return null;
  }
}

async function rpc(env, fn, body) {
  const res = await fetch(`${env.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: env.SUPABASE_KEY,
      Authorization: `Bearer ${env.SUPABASE_KEY}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`rpc ${fn} failed: ${res.status}`);
  return res.json();
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Small status mark drawn with CSS (no emoji): "ok" = blue tick, "info" = grey dot, "warn" = amber bar.
const MARK = {
  ok: '<div class="mark ok"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg></div>',
  warn: '<div class="mark warn"><span>!</span></div>',
  none: "",
};

function page(title, { mark = "none", heading, text = "", item = "", form = "" }, status = 200) {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>${esc(title)} · Research Radar</title>
<style>
  body{margin:0;background:#f4f5f7;color:#1c1e21;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}
  .card{max-width:440px;margin:14vh auto 0;background:#fff;border:1px solid #e4e6eb;border-radius:14px;padding:28px 28px 26px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
  .brand{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#65676b;margin-bottom:18px}
  h1{font-size:20px;line-height:1.3;margin:0 0 8px}
  p{color:#4b4f56;line-height:1.55;margin:0}
  .item{margin:16px 0 4px;padding:12px 14px;background:#f7f8fa;border-left:3px solid #0b57d0;border-radius:6px;font-weight:600;line-height:1.4}
  button{margin-top:20px;width:100%;font-size:15px;font-weight:600;padding:12px 18px;border:0;border-radius:10px;background:#0b57d0;color:#fff;cursor:pointer}
  button:hover{background:#0a4ab3}
  .mark{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin-bottom:14px}
  .mark.ok{background:#0b57d0}.mark.warn{background:#f5a524;color:#fff;font-weight:800;font-size:20px}
</style></head>
<body><main class="card"><div class="brand">Research Radar</div>${MARK[mark]}
<h1>${esc(heading)}</h1>${text ? `<p>${esc(text)}</p>` : ""}${item ? `<div class="item">${esc(item)}</div>` : ""}${form}
</main></body></html>`;
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
}

const problem = (heading, status = 400) =>
  page("Link problem", { mark: "warn", heading, text: "This link may be old, already used, or incomplete." }, status);
const already = (act, headline = "") =>
  page("Already recorded", { mark: "ok", heading: "Already recorded", text: act ? act.done : "You've already used this link.", item: headline });

// A real person clicking a link sends Sec-Fetch-Mode: navigate; server-side scanners and most
// previewers do not. Anything unsure falls back to the confirm page.
function isBrowserClick(request) {
  const purpose = `${request.headers.get("sec-purpose") || ""} ${request.headers.get("purpose") || ""}`;
  return request.method === "GET" && request.headers.get("sec-fetch-mode") === "navigate" && !/prefetch|prerender|preview/i.test(purpose);
}

async function record(env, claims, act, headline) {
  const result = await rpc(env, "record_feedback", { p_nonce: claims.n, p_item: claims.i, p_run: claims.r, p_action: claims.a });
  if (result === "ok") return page("Done", { mark: "ok", heading: act.done, item: headline, text: "You can close this tab." });
  if (result === "used") return already(act, headline);
  if (result === "expired") return problem("This link has expired", 410);
  return problem("This link isn't valid");
}

export { verifyToken };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const m = url.pathname.match(/^\/f\/([\w.-]+)$/);
    if (!m) return new Response("Research Radar feedback endpoint.", { status: 200, headers: { "X-Robots-Tag": "noindex" } });

    const claims = await verifyToken(m[1], env.FEEDBACK_SIGNING_SECRET);
    if (!claims) return problem("This link isn't valid", 400);
    if (claims.expired) return problem("This link has expired", 410);
    const act = ACTIONS[claims.a];

    if (request.method === "GET" || request.method === "HEAD") {
      let headline = "";
      try {
        const info = await rpc(env, "feedback_token_info", { p_nonce: claims.n });
        headline = info.headline || "";
        if (info.status === "used") return already(act, headline);
        if (info.status === "expired") return problem("This link has expired", 410);
        if (info.status !== "ok") return problem("This link isn't valid");
        if (isBrowserClick(request)) return await record(env, claims, act, headline);
      } catch {
        return problem("Something went wrong. Please try again later", 502);
      }
      // Not a confirmed human click: show what would be recorded, write nothing.
      return page(act.title, {
        heading: act.ask,
        item: headline,
        form: `<form method="POST"><button type="submit">${esc(act.button)}</button></form>`,
      });
    }

    if (request.method === "POST") {
      try {
        return await record(env, claims, act, "");
      } catch {
        return problem("Something went wrong. Please try again later", 502);
      }
    }
    return new Response("Method not allowed", { status: 405 });
  },
};
