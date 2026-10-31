// Verifies the per-stage START button: one real canvas click must queue exactly one stage.
const fs = require('fs'), path = require('path'), puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const WF = process.argv[2] ? path.resolve(__dirname, '../..', process.argv[2]) : path.resolve(__dirname, '../../photostudio_mixmedia.json');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true, userDataDir: path.join(__dirname, '.p5'),
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-first-run'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  const posted = [];
  await page.setRequestInterception(true);
  page.on('request', (req) => {
    const url = req.url();
    if (req.method() === 'POST' && url.endsWith('/prompt')) {
      posted.push(req.postData() || '');
      return req.respond({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ prompt_id: 'fake-' + posted.length, number: 0, node_errors: {} }) });
    }
    req.continue();
  });

  await page.goto('http://127.0.0.1:8188', { waitUntil: 'networkidle2', timeout: 60000 });
  await page.waitForFunction('window.app && window.comfyAPI', { timeout: 60000 });
  await new Promise((r) => setTimeout(r, 2500));

  const text = fs.readFileSync(WF, 'utf8');
  const info = await page.evaluate(async (t) => {
    const file = new File([t], 'w.json', { type: 'application/json' });
    const d = await window.comfyAPI.json.getDataFromJSON(file);
    await window.app.loadGraphData(d.workflow, true, true, null);
    const out = { nodes: [] };
    for (const n of window.app.graph._nodes) {
      if (!n.type.startsWith('Mixmedia')) continue;
      const run = n.widgets.find((w) => w.name === 'run');
      out.nodes.push({
        id: n.id, type: n.type,
        hasButton: !!n.__mixmediaStart,
        buttonLabel: n.__mixmediaStart ? n.__mixmediaStart.name : null,
        widgets: n.widgets.map((w) => w.name),
        run: run ? run.value : null,
        size: Array.from(n.size),
        buttonSpace: n.__mixmediaStart ? `y=${n.__mixmediaStart.last_y} free=${n.size[1] - (n.__mixmediaStart.last_y ?? 0)}` : null,
      });
    }
    return out;
  }, text);
  console.log('nodes:', JSON.stringify(info, null, 1));

  // центр на ноде этапа 2 и клик по кнопке в её координатах
  const spot = await page.evaluate(() => {
    const node = window.app.graph._nodes.find((n) => n.type === 'MixmediaShot');
    window.app.canvas.centerOnNode(node);
    window.app.canvas.setZoom ? window.app.canvas.setZoom(1) : (window.app.canvas.ds.scale = 1);
    window.app.canvas.centerOnNode(node);
    window.app.canvas.draw(true, true);
    const w = node.__mixmediaStart;
    const ds = window.app.canvas.ds;
    const rect = window.app.canvas.canvas.getBoundingClientRect();
    const gx = node.pos[0] + node.size[0] / 2;
    const gy = node.pos[1] + (w.last_y ?? node.size[1] - 20) + 8;
    return {
      last_y: w.last_y, node: [node.pos[0], node.pos[1]], size: Array.from(node.size),
      scale: ds.scale, offset: Array.from(ds.offset),
      x: rect.left + (gx + ds.offset[0]) * ds.scale,
      y: rect.top + (gy + ds.offset[1]) * ds.scale,
    };
  });
  console.log('click spot:', JSON.stringify(spot));
  await page.mouse.click(spot.x, spot.y);
  await new Promise((r) => setTimeout(r, 3000));

  const state = await page.evaluate(() => {
    const o = {};
    for (const n of window.app.graph._nodes) {
      const run = n.widgets?.find((w) => w.name === 'run');
      if (run) o[n.type] = run.value;
    }
    return o;
  });
  console.log('run flags after click:', JSON.stringify(state));
  console.log('requests captured:', posted.length);

  if (posted.length) {
    const api = JSON.parse(posted[posted.length - 1]).prompt;
    const stages = Object.entries(api).filter(([, v]) => v.class_type.startsWith('Mixmedia'));
    console.log('queued stages:', JSON.stringify(stages.map(([id, v]) => `${id}:${v.class_type}:run=${v.inputs.run}`)));
    console.log('outputs:', JSON.stringify(Object.values(api).filter((v) => v.class_type === 'SaveImage').length));
  }

  await page.screenshot({ path: path.join(__dirname, 'stage-buttons.png') });
  await browser.close();
  if (posted.length !== 1) process.exitCode = 2;
})().catch((e) => { console.error(e); process.exit(1); });
