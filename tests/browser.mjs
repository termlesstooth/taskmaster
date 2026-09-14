// Optional browser smoke test. Requires Node 22+ and an isolated Chrome with
// --headless=new --remote-debugging-port=9223. No npm dependencies.
// Run against a disposable demo database: node tests/browser.mjs http://127.0.0.1:8001
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';

const appUrl=process.argv[2] || 'http://127.0.0.1:8001';
const tabs=await fetch('http://127.0.0.1:9223/json').then(r=>r.json());
const socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
let sequence=0;
const pending=new Map(), errors=[];
socket.addEventListener('message',({data})=>{const msg=JSON.parse(data);if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails.text);if(msg.id){const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(msg.error):p.resolve(msg.result);}});
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);return r.result.value;}
async function waitFor(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,50));}throw new Error('Timed out: '+expression);}
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);}
async function fill(selector,value){await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);}
async function screenshot(name){const {data}=await send('Page.captureScreenshot',{format:'png'});await writeFile('/private/tmp/thread-'+name+'.png',Buffer.from(data,'base64'));}
let checks=0;
async function check(expression,message){assert.equal(await evaluate(expression),true,message);checks++;console.log('PASS',message);}
try {
 await send('Runtime.enable');
 await send('Page.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:appUrl});
 await waitFor('document.querySelectorAll(".task-card").length===11');
 await check('document.querySelector("h1").textContent==="Website redesign"','Project is selected on first load');
 await screenshot('desktop');
 await click('[data-action="view"][data-view="list"]');
 await check('document.querySelectorAll(".list-row").length===11','List includes all nested tasks');
 await click('[data-action="fold-task"][data-id="4"]');
 await check('document.querySelectorAll(".list-row").length===9','Collapsing a story hides every nested level');
 await fill('#task-search','Menu keyboard');
 await check('document.querySelectorAll(".list-row").length===1','Search finds a nested task even with collapsed ancestors');
 await fill('#task-search','');
 await click('[data-action="view"][data-view="daily"]');
 await check('document.querySelectorAll(".daily-task").length===9','Daily excludes completed tasks');
 await screenshot('daily');
 await click('[data-action="new-task"]');
 await fill('[name="title"]','Browser test epic');
 await fill('[name="description"]','A real save through the task form.');
 await fill('[name="due_date"]','2026-09-14');
 await click('#task-form [type="submit"]');
 await waitFor('!document.querySelector("dialog").open && !state.busy');
 await check('state.tasks.some(t=>t.title==="Browser test epic")','Task creation saves through the Python API');
 const epic=await evaluate('state.tasks.find(t=>t.title==="Browser test epic").id');
 await click(`[data-action="edit-task"][data-id="${epic}"]`);
 await click(`[data-action="child-task"][data-id="${epic}"]`);
 await waitFor('document.querySelector("#task-form")?.dataset.id==="" && !state.busy');
 await fill('[name="title"]','Browser test story');
 await click('#task-form [type="submit"]');
 await waitFor('!document.querySelector("dialog").open && !state.busy');
 await check(`state.tasks.find(t=>t.title==='Browser test story').parent_id===${epic}`,'Subtask inherits its project and parent');
 await click('[data-action="statuses"]');
 await fill('#new-status-form [name="name"]','Bug');
 await click('#new-status-form [type="submit"]');
 await waitFor('state.statuses.some(s=>s.name==="Bug") && !state.busy');
 await check('document.querySelectorAll(".status-form").length===5','Custom status is added to the project');
 const bug=await evaluate('state.statuses.find(s=>s.name==="Bug").id');
 await fill(`.status-form[data-id="${bug}"] [name="name"]`,'Fixed');
 await click(`.status-form[data-id="${bug}"] [name="is_done"]`);
 await click(`.status-form[data-id="${bug}"] [type="submit"]`);
 await waitFor(`state.statuses.find(s=>s.id===${bug}).name==='Fixed' && !state.busy`);
 await check(`state.statuses.find(s=>s.id===${bug}).is_done===1`,'Custom status can be renamed and marked complete');
 await click('[aria-label="Close dialog"]');
 await click('[data-action="view"][data-view="board"]');
 await check('document.querySelectorAll(".board-column").length===5','Custom status appears as a board column');
 await evaluate(`(() => {const card=document.querySelector('[data-task-id="${epic}"]'), col=document.querySelector('[data-status-id="${bug}"]');const transfer=new DataTransfer();card.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));col.dispatchEvent(new DragEvent('dragover',{bubbles:true,dataTransfer:transfer}));col.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));})()`);
 await waitFor(`!state.busy && state.tasks.find(t=>t.id===${epic}).status_id===${bug}`);
 await check(`document.querySelector('[data-status-id="${bug}"] [data-task-id="${epic}"]')!==null`,'Dropping a card moves it into the new status');
 await send('Page.reload');
 await waitFor(`typeof state!=='undefined' && state.tasks.some(t=>t.id===${epic})`);
 await check(`state.tasks.find(t=>t.id===${epic}).status_id===${bug}`,'Task status survives a full page reload');
 await click('[data-action="new-space"]');
 await fill('#node-form [name="name"]','Browser test space');
 await click('#node-form [type="submit"]');
 await waitFor('!document.querySelector("dialog").open && !state.busy');
 await check('document.querySelector("h1").textContent==="Browser test space"','Creating a space selects its overview');
 await click('[data-action="new-task"]');
 await fill('#node-form [name="name"]','Browser test project');
 await click('#node-form [type="submit"]');
 await waitFor('!document.querySelector("dialog").open && !state.busy');
 await check('node(state.selected).kind==="project" && node(node(state.selected).parent_id).name==="Browser test space"','Empty-space task action creates a nested project');
 await check('document.querySelectorAll(".board-column").length===4','New project has a ready-to-use workflow');
 await click('.nav-select[data-id="2"]');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await screenshot('mobile');
 await check('document.documentElement.scrollWidth===390','Phone layout has no page-level horizontal overflow');
 await click('[data-action="menu"]');
 await check('document.querySelector("#sidebar").classList.contains("mobile-open")','Mobile navigation opens');
 await click('[data-action="daily-global"]');
 await check('!document.querySelector("#sidebar").classList.contains("mobile-open") && state.view==="daily"','Mobile navigation closes after selecting My day');
 await screenshot('mobile-daily');
 await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
 await check('getComputedStyle(document.querySelector("#view-content")).animationName==="none"','Reduced motion disables view animation');
 assert.deepEqual(errors,[],'No browser runtime errors');
 console.log(`${checks} browser checks passed; no runtime errors. Screenshots: /private/tmp/thread-*.png`);
} finally {socket.close();}
