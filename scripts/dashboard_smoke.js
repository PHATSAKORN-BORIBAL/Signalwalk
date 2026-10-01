// Headless smoke test for the dashboard using jsdom (dev-only, not part of the runtime).
// Usage: node scripts/dashboard_smoke.js http://127.0.0.1:8000     (server in simulate mode)
// Needs: npm install jsdom. Canvas drawing is stubbed, so this checks that the JavaScript
// runs and builds the right DOM. It does NOT check how anything looks.
const { JSDOM, VirtualConsole } = require("jsdom");
const base = process.argv[2] || "http://127.0.0.1:8000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const problems = [];
const check = (cond, msg) => { console.log((cond ? "PASS  " : "FAIL  ") + msg); if (!cond) problems.push(msg); };

(async () => {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => problems.push("jsdomError: " + e.message));
  vc.on("error", (...a) => problems.push("console.error: " + a.join(" ")));
  const html = await (await fetch(base + "/")).text();
  const dom = new JSDOM(html, {
    url: base + "/", runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = (u, o) => fetch(new URL(u, base), o);
      const noop = () => {};
      const ctx = new Proxy({}, { get: (t, k) => (k === "createImageData" ? (a, b) => ({ data: new Uint8ClampedArray(a * b * 4) }) : k in t ? t[k] : noop),
                                  set: (t, k, v) => { t[k] = v; return true; } });
      w.HTMLCanvasElement.prototype.getContext = () => ctx;
      Object.defineProperty(w.HTMLElement.prototype, "clientWidth", { get() { return 800; } });
      w.confirm = () => true;
    },
  });
  const d = dom.window.document;
  const q = (s) => d.querySelector(s), qa = (s) => [...d.querySelectorAll(s)];
  const until = async (fn, ms = 8000) => { for (let t = 0; t < ms && !fn(); t += 100) await sleep(100); };

  await until(() => q("#plan-name").textContent.length > 0);
  check(/apartment/i.test(q("#plan-name").textContent), "plan name shown: " + q("#plan-name").textContent);
  check(!q("#mode-badge").hidden && /Simulation/.test(q("#mode-badge").textContent), "simulation badge: " + q("#mode-badge").textContent);
  check(!q("#btn-auto").hidden, "auto-survey button visible in simulation mode");
  check(/Nothing measured|Click on the plan/.test(q("#summary").textContent + q("#zones").textContent), "empty state shown before any measurement");
  check(q("#btn-undo").disabled, "undo disabled with no measurements");

  q("#btn-auto").click();
  await until(() => qa("#points li").length >= 10);
  check(qa("#points li").length === 10, "auto-survey adds 10 measurements: " + qa("#points li").length);
  check(/^\d+%/.test(q("#summary .big").textContent), "coverage headline: " + q("#summary .big").textContent);
  check(qa("#summary .stack i").length === 4, "stacked coverage bar has 4 segments");
  check(qa("#advice .adv-item .dot:not(.ext):not(.q)").length >= 1, "router advice items shown");
  check(/extender/i.test(q("#advice").textContent), "extender advice shown");
  check(qa("#rooms .room").length === 6, "room report card has 6 rooms");
  check(qa("#zones .zone").length >= 1, "at least one weak/dead zone listed");
  check(/dB/.test(q("#summary").textContent), "map-error line shown");

  // click on the canvas = take one more measurement at that spot
  const canvas = q("#map");
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 533 });
  canvas.dispatchEvent(new dom.window.MouseEvent("click", { clientX: 400, clientY: 266, bubbles: true }));
  await until(() => qa("#points li").length >= 11);
  check(qa("#points li").length === 11, "click on the map adds a measurement");
  check(/dBm at \(/.test(q("#toast").textContent), "toast confirms it: " + q("#toast").textContent);

  canvas.dispatchEvent(new dom.window.MouseEvent("mousemove", { clientX: 100, clientY: 100, bubbles: true }));
  check(!q("#tooltip").hidden && /dBm ±/.test(q("#tooltip").textContent), "hover tooltip: " + q("#tooltip").textContent);

  q("#opt-confidence").click(); q("#opt-advice").click();
  check(true, "toggling confidence / advice does not throw");

  qa("#points .btn")[0].click();
  await until(() => qa("#points li").length === 10);
  check(qa("#points li").length === 10, "delete removes one measurement");
  q("#btn-undo").click();
  await until(() => qa("#points li").length === 9);
  check(qa("#points li").length === 9, "undo removes the last measurement");

  q("#btn-reset").click();
  await until(() => qa("#points li").length === 0);
  check(qa("#points li").length === 0 && /Nothing measured/.test(q("#zones").textContent), "reset clears everything");

  canvas.dispatchEvent(new dom.window.MouseEvent("click", { clientX: 5000, clientY: 5000, bubbles: true }));
  await until(() => /outside/.test(q("#toast").textContent));
  check(/outside/i.test(q("#toast").textContent), "out-of-plan click shows an error toast: " + q("#toast").textContent);

  check(problems.filter((p) => /rror/.test(p)).length === 0, "no JS errors: " + JSON.stringify(problems.filter((p) => /rror/.test(p))));
  dom.window.close();
  process.exit(problems.length ? 1 : 0);
})().catch((e) => { console.error("smoke test crashed:", e); process.exit(2); });
