// Loads the generated workflows into the real ComfyUI frontend (headless Chrome)
// and reports whether the browser accepts them as workflows.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URL = 'http://127.0.0.1:8188';
const ROOT = path.resolve(__dirname, '../..');

const files = process.argv.slice(2);

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    userDataDir: path.join(__dirname, '.chrome-profile'),
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-crash-reporter', '--disable-breakpad', '--no-first-run', '--no-default-browser-check'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const logs = [];
  page.on('console', (m) => logs.push(`${m.type()}: ${m.text()}`));
  page.on('pageerror', (e) => logs.push(`pageerror: ${e.message}`));

  await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.waitForFunction('window.app && window.comfyAPI && window.comfyAPI.json', { timeout: 60000 });
  await new Promise((r) => setTimeout(r, 3000));

  for (const rel of files) {
    const abs = path.resolve(ROOT, rel);
    const text = fs.readFileSync(abs, 'utf8');
    const res = await page.evaluate(async (text, name) => {
      const out = {};
      const file = new File([text], name, { type: 'application/json' });
      let parsed;
      try {
        parsed = await window.comfyAPI.json.getDataFromJSON(file);
      } catch (e) {
        out.parseError = String(e);
        return out;
      }
      if (!parsed) return { parseError: 'getDataFromJSON returned undefined' };
      out.keys = Object.keys(parsed);
      if (!parsed.workflow) return out;
      out.workflowId = parsed.workflow.id;
      try {
        await window.app.loadGraphData(parsed.workflow, true, true, null);
        out.loaded = true;
      } catch (e) {
        out.loadError = String(e && e.message ? e.message : e);
      }
      const g = window.app.graph;
      out.nodes = g._nodes.length;
      out.missing = g.nodes.filter((n) => !n.constructor.nodeData).map((n) => n.type);
      out.types = g.nodes.map((n) => n.type);
      out.widgetCounts = g.nodes.map((n) => `${n.type}:${(n.widgets || []).length}`);
      return out;
    }, text, path.basename(rel));

    console.log(`\n=== ${rel}`);
    console.log(JSON.stringify(res, null, 2));
  }

  await page.screenshot({ path: path.join(__dirname, 'comfy-loaded.png') });
  console.log('\nconsole errors:', logs.filter((l) => l.startsWith('error') || l.startsWith('pageerror')).slice(0, 10));
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
