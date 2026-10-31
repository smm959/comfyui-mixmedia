// Loads each workflow into the real frontend and prints, for every MixMedia node,
// which input links survived and what widget values ended up where.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async () => {
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: true, userDataDir: path.join(__dirname, '.p2'),
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-crash-reporter', '--disable-breakpad', '--no-first-run'],
  });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:8188', { waitUntil: 'networkidle2', timeout: 60000 });
  await p.waitForFunction('window.app && window.comfyAPI', { timeout: 60000 });
  await new Promise((r) => setTimeout(r, 2500));

  for (const f of process.argv.slice(2)) {
    const text = fs.readFileSync(path.resolve(__dirname, '../..', f), 'utf8');
    const res = await p.evaluate(async (t) => {
      const file = new File([t], 'w.json', { type: 'application/json' });
      const d = await window.comfyAPI.json.getDataFromJSON(file);
      await window.app.loadGraphData(d.workflow, true, true, null);
      const out = [];
      for (const n of window.app.graph.nodes) {
        if (!n.type.startsWith('Mixmedia')) continue;
        const linked = n.inputs.filter((i) => i.link != null).map((i) => `${n.inputs.indexOf(i)}:${i.name}`);
        const outs = (n.outputs || []).map((o, i) => `${i}:${o.name}=${(o.links || []).length}`);
        out.push({
          id: n.id, type: n.type, linked,
          widgets: Object.fromEntries((n.widgets || []).map((w) => [w.name, w.value])),
          outputs: outs,
        });
      }
      return out;
    }, text);
    console.log('===', f);
    console.log(JSON.stringify(res, null, 1));
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
