const path=require('path'), puppeteer=require('puppeteer-core');
const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async()=>{
 const b=await puppeteer.launch({executablePath:CHROME,headless:true,userDataDir:path.join(__dirname,'.p'),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-crash-reporter','--disable-breakpad','--no-first-run']});
 const p=await b.newPage();
 await p.goto('http://127.0.0.1:8188',{waitUntil:'networkidle2',timeout:60000});
 await p.waitForFunction('window.app && window.LiteGraph',{timeout:60000});
 await new Promise(r=>setTimeout(r,2500));
 const out=await p.evaluate(()=>{
   const r={};
   for (const t of ['MixmediaShot','MixmediaStudio','MixmediaRetake']) {
     const n=window.LiteGraph.createNode(t);
     r[t]={inputs:n.inputs.map((i,idx)=>idx+':'+i.name+'/'+i.type), widgets:n.widgets.map(w=>w.name)};
   }
   return r;
 });
 console.log(JSON.stringify(out,null,1));
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
