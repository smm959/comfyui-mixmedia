// Builds the API prompt in the real frontend, drops the output nodes and asks the server
// to validate the rest: catches missing/empty LoadImage files without spending money.
const fs=require('fs'), path=require('path'), puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:true,userDataDir:path.join(__dirname,'.p5'),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-crash-reporter','--disable-breakpad','--no-first-run']});
 const p=await b.newPage();
 await p.goto('http://127.0.0.1:8188',{waitUntil:'networkidle2',timeout:60000});
 await p.waitForFunction('window.app && window.comfyAPI',{timeout:60000});
 await new Promise(r=>setTimeout(r,2500));
 for (const f of process.argv.slice(2)) {
  const text=fs.readFileSync(path.resolve(__dirname,'../..',f),'utf8');
  const prompt=await p.evaluate(async(t)=>{
    const file=new File([t],'w.json',{type:'application/json'});
    const d=await window.comfyAPI.json.getDataFromJSON(file);
    await window.app.loadGraphData(d.workflow,true,true,null);
    const pr=await window.app.graphToPrompt();
    const api=pr.output||{};
    for (const [id,v] of Object.entries(api)) if (['SaveImage','PreviewAny'].includes(v.class_type)) delete api[id];
    return api;
  }, text);
  console.log('===', f);
  for (const [id,v] of Object.entries(prompt)) {
    const extra = v.class_type==='LoadImage' ? ' image='+JSON.stringify(v.inputs.image) : '';
    console.log(' ', id, v.class_type, extra);
  }
  const res=await p.evaluate(async(api)=>{
    const r=await fetch('/prompt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:api,client_id:'validate-probe'})});
    return {status:r.status, body:await r.text()};
  }, prompt);
  console.log(' ->', res.status, res.body.slice(0,700));
 }
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
