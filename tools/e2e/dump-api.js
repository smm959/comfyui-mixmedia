// Dumps the API-format prompt of a UI workflow (what the server would validate/execute).
const fs=require('fs'), path=require('path'), puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:true,userDataDir:path.join(__dirname,'.p6'),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-crash-reporter','--disable-breakpad','--no-first-run']});
 const p=await b.newPage();
 await p.goto('http://127.0.0.1:8188',{waitUntil:'networkidle2',timeout:60000});
 await p.waitForFunction('window.app && window.comfyAPI',{timeout:60000});
 await new Promise(r=>setTimeout(r,2500));
 const text=fs.readFileSync(path.resolve(__dirname,'../..',process.argv[2]),'utf8');
 const api=await p.evaluate(async(t)=>{
   const file=new File([t],'w.json',{type:'application/json'});
   const d=await window.comfyAPI.json.getDataFromJSON(file);
   await window.app.loadGraphData(d.workflow,true,true,null);
   const pr=await window.app.graphToPrompt();
   return pr.output;
 }, text);
 console.log(JSON.stringify(api,null,1));
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
