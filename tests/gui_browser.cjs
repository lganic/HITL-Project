// Optional developer check: npm install --no-save playwright; npx playwright install chromium
// Run: node tests/gui_browser.cjs (Python 3.11+ must be available).
const { chromium: playwright }=require(process.env.HITL_PLAYWRIGHT_MODULE || 'playwright');
const {spawn}=require('child_process'), fs=require('fs'), os=require('os'), path=require('path');
const root=path.resolve(__dirname,'..');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'hitl-gui-browser-'));
const server=spawn(process.env.PYTHON || (process.platform==='win32'?'python':'python3'),['-m','hitl_se.gui','--no-browser','--workspace',temp+'/live','--demo-workspace',temp+'/demo'],{cwd:root});
process.on('exit',()=>server.kill());
const launchUrl=new Promise((resolve,reject)=>{let output='';server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:[^\s]+/);if(match)resolve(match[0]);});server.on('error',reject);server.stderr.on('data',chunk=>process.stderr.write(chunk));});
(async()=>{
const browser=await playwright.launch({...(process.env.HITL_BROWSER_EXECUTABLE?{executablePath:process.env.HITL_BROWSER_EXECUTABLE}:{}),args:['--disable-gpu','--disable-software-rasterizer','--use-gl=disabled','--use-angle=disabled','--no-sandbox','--disable-dev-shm-usage','--no-zygote','--single-process'],headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(await launchUrl);
await page.getByRole('button',{name:'Create your first project'}).click();
await page.getByRole('textbox',{name:'Project name'}).fill('Unicode normalizer · GUI check');
await page.getByRole('button',{name:'Create project',exact:true}).click();
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Human requirements checker',exact:true}).waitFor();
await page.screenshot({path:path.join(root,'docs/gui-preview.png'),fullPage:false});
await page.getByLabel('Reason, corrections, or question').fill('Verified Unicode and invalid-input acceptance requirements in the GUI.');
await page.getByLabel('I reviewed this checkpoint').check();
await page.getByRole('button',{name:'Submit decision',exact:true}).click();
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).waitFor({state:'visible'});
await page.waitForFunction(()=>!document.querySelector('#run').disabled);
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Human architectural direction',exact:true}).waitFor();
await page.getByLabel('Choose an option').selectOption('library');
await page.getByLabel('Reason, corrections, or question').fill('A pure Python library matches the normalizer requirements.');
await page.getByLabel('I reviewed this checkpoint').check();
await page.getByRole('button',{name:'Submit decision',exact:true}).click();
await page.waitForFunction(()=>!document.querySelector('#run').disabled);
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Human architectural decision',exact:true}).waitFor();
await page.getByLabel('Choose an option').selectOption('library');
await page.getByLabel('Reason, corrections, or question').fill('Accept the refined library architecture.');
await page.getByLabel('I reviewed this checkpoint').check();
await page.getByRole('button',{name:'Submit decision',exact:true}).click();
await page.waitForFunction(()=>!document.querySelector('#run').disabled);
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Development checkpoint 1: approach and evaluation scope',exact:true}).waitFor();
await page.getByLabel('Choose an option').selectOption('A');
await page.getByLabel('Reason, corrections, or question').fill('Review plan A and authorize fixed, bounded fixture checks.');
await page.getByLabel('I authorize the displayed').check();
await page.getByLabel('I reviewed this checkpoint').check();
await page.getByRole('button',{name:'Submit decision',exact:true}).click();
await page.waitForFunction(()=>!document.querySelector('#run').disabled);
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Development checkpoint 2: comparative decision',exact:true}).waitFor();
await page.getByRole('button',{name:'Code & comparison',exact:true}).click();
await page.getByRole('heading',{name:'Candidate A',exact:true}).waitFor();
if(await page.locator('.source').count()<2)throw Error('Candidate source missing');
await page.screenshot({path:path.join(root,'docs/gui-code-preview.png'),fullPage:false});
await page.getByRole('button',{name:'Tests & evidence',exact:true}).click();
await page.locator('.badge.fail').waitFor();
await page.getByRole('button',{name:'Workflow tasks',exact:true}).click();
if(await page.locator('tr.task-current').count()!==1)throw Error('Current task missing');
await page.getByRole('button',{name:'All artifacts',exact:true}).click();
await page.getByLabel('Artifact version').selectOption({index:1});
await page.locator('#artifact-body .eyebrow').waitFor();
await page.getByRole('button',{name:'Activity',exact:true}).click();
await page.getByRole('heading',{name:'Activity & decisions',exact:true}).waitFor();
await page.getByRole('button',{name:'Human checkpoint',exact:true}).click();

await page.locator('select[name=action]').selectOption('modify');
await page.getByLabel('Reason, corrections, or question').fill('Correct candidate B Unicode handling and rerun both candidate checks.');
await page.getByLabel('I authorize the displayed').check();
await page.getByLabel('I reviewed this checkpoint').check();
await page.getByRole('button',{name:'Submit decision',exact:true}).click();
await page.waitForFunction(()=>!document.querySelector('#run').disabled);
await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
await page.getByRole('heading',{name:'Development checkpoint 2: comparative decision',exact:true}).waitFor();
await page.getByRole('button',{name:'Tests & evidence',exact:true}).click();
await page.locator('.badge.pass').first().waitFor();
if(await page.locator('.badge.fail').count())throw Error('Modified candidate still fails');
// Complete all remaining human checkpoints through the rendered forms.
await page.getByRole('button',{name:'Human checkpoint',exact:true}).click();
for(let i=0;i<15;i++) {
  const meta=await page.locator('#project-meta').innerText();
  if(meta.includes('review.closed'))break;
  await page.locator('#decision-form').waitFor();
  const gate=await page.locator('#decision-form').getAttribute('data-gate');
  await page.locator('select[name=action]').selectOption('approve');
  await page.locator('#decision-form textarea[name=feedback]').fill('Browser verification: reviewed the current proposal and evidence.');
  if(meta.includes('dev.final'))await page.locator('select[name=selection]').selectOption('A');
  if(meta.includes('deploy.manual')) {
    await page.locator('select[name=status]').selectOption('deferred');
    await page.locator('textarea[name=record]').fill('Browser test: no actual deployment was performed.');
  }
  if(meta.includes('review.feedback')) {
    await page.locator('textarea[name=demo_notes]').fill('Verified the complete human-driven GUI workflow.');
    await page.locator('select[name=outcome]').selectOption('close');
  }
  await page.getByLabel('I reviewed this checkpoint').check();
  await page.getByRole('button',{name:'Submit decision',exact:true}).click();
  if(meta.includes('review.feedback')) {
    await page.waitForFunction(()=>document.querySelector('#project-meta').textContent.includes('review.closed'));
    break;
  }
  await page.waitForFunction(()=>!document.querySelector('#run').disabled);
  await page.getByRole('button',{name:'Run to next checkpoint',exact:true}).click();
  await page.waitForFunction(g=>document.querySelector('#decision-form')?.dataset.gate && document.querySelector('#decision-form').dataset.gate!==g,gate);
}
if(!(await page.locator('#project-meta').innerText()).includes('review.closed'))throw Error('GUI did not close iteration');
await page.getByLabel('Export type').selectOption('tested');
const downloading=page.waitForEvent('download');
await page.getByRole('button',{name:'Download',exact:true}).click();
const download=await downloading;
if(download.suggestedFilename()!=='tested-source.zip')throw Error('Download missing');
await page.getByRole('button',{name:'Provider & sandbox settings',exact:true}).click();
await page.locator('#settings-form input[name=model]').fill('test-model');
await page.getByRole('button',{name:'Save settings',exact:true}).click();
await page.locator('#settings-dialog').waitFor({state:'hidden'});
await page.setViewportSize({width:390,height:844});
await page.screenshot({path:path.join(root,'docs/gui-mobile-preview.png'),fullPage:true});
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
if(overflow)throw Error('Mobile layout overflows viewport');
console.log('PASS: Complete browser workflow, modification loop, all review tabs, settings save, download, responsive layout.');
console.log('Browser errors:',errors);
await browser.close();
server.kill();
if(errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);server.kill();process.exit(1)});
