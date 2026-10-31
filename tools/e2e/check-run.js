// Verifies which output nodes a single Queue Prompt would run in a multi-stage workflow.
const fs=require('fs'), path=require('path'), puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:true,userDataDir:path.join(__dirname,'.p4'),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-crash-reporter','--disable-breakpad','--no-first-run']});
 const p=await b.newPage();
 await p.goto('http://127.0.0.1:8188',{waitUntil:'networkidle2',timeout:60000});
 await p.waitForFunction('window.app && window.comfyAPI',{timeout:60000});
 await new Promise(r=>setTimeout(r,2500));
 for (const f of process.argv.slice(2)) {
  const text=fs.readFileSync(path.resolve(__dirname,'../..',f),'utf8');
  const res=await p.evaluate(async(t)=>{
    const file=new File([t],'w.json',{type:'application/json'});
    const d=await window.comfyAPI.json.getDataFromJSON(file);
    await window.app.loadGraphData(d.workflow,true,true,null);
    const out={};
    out.nodes=window.app.graph.nodes.map(n=>`${n.id}:${n.type}${n.mode?'(mode '+n.mode+')':''}`);
    out.muted=window.app.graph.nodes.filter(n=>n.mode!==0).map(n=>`${n.id}:${n.type}`);
    const pr=await window.app.graphToPrompt();
    const api=pr.output||{};
    const outputNodes=Object.entries(api).filter(([id,v])=>['SaveImage','PreviewAny'].includes(v.class_type));
    out.apiOutputs=outputNodes.map(([id,v])=>`${id}:${v.class_type}`);
    out.apiNodes=Object.values(api).map(v=>v.class_type);
    // which outputs would the server actually run: output nodes and their ancestors
    return out;
  }, text);
  console.log('===', f);
  console.log(JSON.stringify(res,null,1));
 }
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
