'use strict';
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = v => JSON.stringify(v, null, 2);
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('session') || sessionStorage.getItem('hitl-session') || '';
if (token) sessionStorage.setItem('hitl-session', token);
history.replaceState(null, '', location.pathname);
let mode = fragment.get('mode') === 'live' ? 'live' : 'demo';
let selected = null, snapshot = null, activeTab = 'review', renderKey = '', refreshing = false, viewGeneration = 0;
const cache = new Map();
$('#mode').value = mode;
function showError(error) { $('#error').textContent = error.message || error; $('#error').hidden = false; }
async function api(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-HITL-Session': token, ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function query(path, extra={}) { return path + '?' + new URLSearchParams({mode, ...(selected ? {project:selected} : {}), ...extra}); }
function status(p) { return p.state === 'review.closed' ? 'complete' : (snapshot.jobs[p.id]?.status === 'running' ? 'running' : p.status); }
function badge(value) { return `<span class="badge ${esc(value)}">${esc(value)}</span>`; }
async function refresh(force=false) {
  if (refreshing) return;
  refreshing = true;
  const requestMode = mode, requestProject = selected;
  try {
    const data = await api(query('/api/state'));
    if (requestMode !== mode || requestProject !== selected) return;
    snapshot = data;
    $('#connection').textContent = '● Connected locally';
    $('#notice').textContent = mode === 'demo' ? 'INTERACTIVE DEMO · Scripted agents, a fixed normalizer task, and real checks on allowlisted fixture code. You make every decision. Nothing is deployed.' : 'LIVE WORKSPACE · Agents use your configured provider; API charges may apply. Generated code runs in Docker after your explicit approval.';
    renderProjects();
    const counts = ['waiting','running','ready','complete'].map(s => data.projects.filter(p => status(p) === s).length);
    $('#metrics').innerHTML = counts.map((n,i)=>`<div class="metric"><strong>${n}</strong><span>${['Needs your review','Work in progress','Ready to continue','Completed'][i]}</span></div>`).join('');
    if (!selected && data.projects.length) { selected = data.projects[0].id; renderKey = ''; return; }
    $('#empty').hidden = Boolean(selected); $('#detail').hidden = !selected;
    if (data.project) {
      renderProject();
      const key = [mode,selected,data.project.revision,data.gate?.id,activeTab,data.artifacts.length,JSON.stringify(data.jobs[selected])].join('|');
      if (force || key !== renderKey) {
        // A question response changes artifacts without replacing the gate. Preserve the user's draft.
        const form = $('#decision-form');
        const draft = form && form.dataset.gate === data.gate?.id ? Object.fromEntries(new FormData(form)) : null;
        renderKey = key;
        await renderPanel(draft);
      }
    }
  } catch(error) { $('#connection').textContent = 'Connection needs attention'; showError(error); }
  finally { refreshing = false; }
}
function renderProjects() {
  const filter = $('#search').value.toLowerCase();
  $('#project-count').textContent = snapshot.projects.length;
  $('#projects').innerHTML = snapshot.projects.filter(p=>p.name.toLowerCase().includes(filter)).map(p=>`<button class="project-card ${p.id===selected?'selected':''}" data-project="${esc(p.id)}"><strong>${esc(p.name)}</strong><small>${esc(p.state)} · ${esc(status(p))}</small></button>`).join('');
}
function renderProject() {
  const p = snapshot.project, busy = snapshot.jobs[selected]?.status === 'running' || p.status === 'running';
  $('#project-name').textContent = p.name; $('#project-goal').textContent = p.goal;
  $('#project-meta').textContent = `ITERATION ${p.iteration} / ${p.state}`;
  $('#project-status').outerHTML = `<span id="project-status" class="badge ${esc(status(p))}">${esc(status(p))}</span>`;
  const visited = new Set(snapshot.events.filter(e=>e.type==='step_completed').map(e=>e.state));
  $('#workflow').innerHTML = Object.entries(snapshot.workflows).map(([phase,states],i)=>`<div class="phase ${states.includes(p.state)?'current':states.some(s=>visited.has(s))?'visited':''}">${String(i+1).padStart(2,'0')} ${phase}<small>${states.includes(p.state)?'Current phase':states.some(s=>visited.has(s))?'Previously visited':'Upcoming'}</small></div>`).join('');
  $('#run').disabled = $('#step').disabled = busy || p.status !== 'ready' || p.state === 'review.closed';
  $('#recover').hidden = !['failed','running'].includes(p.status);
  $('#recover').disabled = busy && snapshot.jobs[selected]?.status === 'running';
  $('#rework').hidden = !p.state.startsWith('test.'); $('#rework').disabled = busy;
  const job = snapshot.jobs[selected];
  $('#job').className = job ? 'job-'+job.status : '';
  $('#job').textContent = p.error || (job?.status === 'running' ? `Working: ${job.state || job.operation}… You can inspect other projects while this runs.` : job?.error || (job?.status === 'done' ? 'Operation finished. Review the current state before continuing.' : ''));
  if(p.error) $('#job').className='job-failed';
  const values = {audit:true, accepted:Boolean(p.data.merge_decision || p.data.selected_candidate || p.iteration > 1), tested:Boolean(p.data.test_bundle)};
  for(const option of $('#export-kind').options) option.disabled = !values[option.value];
  if($('#export-kind').selectedOptions[0].disabled) $('#export-kind').value='audit';
}
async function artifact(id) {
  if(!cache.has(id)) cache.set(id, await api(query('/api/artifact',{id})));
  return cache.get(id);
}
function jsonBlock(value) { return `<pre>${esc(pretty(value))}</pre>`; }
function sourceFiles(files) {
  return Object.entries(files || {}).map(([name,text])=>`<div class="file-label">${esc(name)}</div><pre class="source">${esc(text)}</pre>`).join('') || '<p class="muted">No source files in this snapshot.</p>';
}
function artifactContent(art) {
  const p = art.payload || art.content;
  let html = `<div class="eyebrow">${esc(art.kind)} ${art.version ? '· VERSION '+art.version : ''}</div>`;
  if(p.files) html += sourceFiles(p.files);
  if(p.test_files) html += '<h4>Proposed tests</h4>'+sourceFiles(p.test_files);
  if(p.diff !== undefined) html += diffBlock(p.diff);
  if(p.checks) html += evidenceContent(p);
  const rest = Object.fromEntries(Object.entries(p).filter(([k])=>!['files','test_files','diff','checks','stdout','stderr'].includes(k)));
  if(Object.keys(rest).length) html += jsonBlock(rest);
  if(!p.checks) for(const k of ['stdout','stderr']) if(p[k]) html += `<h4>${k}</h4><pre>${esc(p[k])}</pre>`;
  return html;
}
function diffBlock(diff) {
  return `<pre class="diff">${diff ? diff.split('\n').map(line=>`<span class="${line.startsWith('+')?'added':line.startsWith('-')?'removed':'context'}">${esc(line)||' '}</span>`).join('') : 'Candidates have identical source.'}</pre>`;
}
function evidenceContent(p) {
  return `<div class="row"><h3>Measured execution</h3>${badge(p.passed?'pass':'fail')}</div><p class="hint">Exit code: ${esc(p.exit_code)} · Duration: ${esc(p.duration_seconds)}s · ${esc(p.execution_mode || p.tool || '')}</p>${jsonBlock(p.checks)}${['stdout','stderr'].map(k=>`<details ${p[k]?'open':''}><summary>Raw ${k}</summary><pre>${esc(p[k] || '(empty)')}</pre></details>`).join('')}${p.stopped?`<p class="error">Stopped: ${esc(p.stopped)}</p>`:''}`;
}
async function renderPanel(draft=null) {
  const generation = ++viewGeneration;
  const data = snapshot, p = data.project, panel = $('#panel');
  if(activeTab === 'review') { renderReview(draft); return; }
  if(activeTab === 'tasks') {
    const seen = new Set(data.events.filter(e=>e.type==='step_completed'||e.type==='human_decision').map(e=>e.state));
    panel.innerHTML = `<div class="panel-card"><h3>All workflow tasks</h3><p class="muted">The current task is authoritative. Previously visited tasks can repeat after feedback; upcoming branches are conditional.</p>${Object.entries(data.workflows).map(([phase,states])=>`<h4>${esc(phase.toUpperCase())}</h4><div class="table-wrap"><table><thead><tr><th>Task</th><th>Owner</th><th>State</th></tr></thead><tbody>${states.map(s=>`<tr class="${s===p.state?'task-current':''}"><td class="task-code">${esc(s)}</td><td>${data.human_states.includes(s)?'Human':'Engine / agent'}</td><td>${s===p.state?badge(status(p)):seen.has(s)?'Previously performed':'Pending / conditional'}</td></tr>`).join('')}</tbody></table></div>`).join('')}</div>`; return;
  }
  if(activeTab === 'history') {
    panel.innerHTML = `<div class="panel-card"><h3>Activity & decisions</h3>${[...data.events].reverse().map(e=>`<div class="activity"><strong>${esc(e.type.replaceAll('_',' '))}</strong><small>${esc(e.created)} · ${esc(e.state)}${e.payload.actor?' · '+esc(e.payload.actor):''}</small>${e.payload.feedback?`<p>${esc(e.payload.feedback)}</p>`:''}<details><summary>Event details</summary>${jsonBlock(e.payload)}</details></div>`).join('')}</div>`; return;
  }
  if(activeTab === 'artifacts') {
    panel.innerHTML = `<div class="panel-card"><h3>Versioned artifacts</h3><p class="muted">Inspect any version, including earlier iterations and answers to your questions.</p><select id="artifact-select" aria-label="Artifact version"><option value="">Choose an artifact…</option>${[...data.artifacts].reverse().map(a=>`<option value="${esc(a.id)}">${esc(a.kind)} · v${a.version} · iteration ${a.iteration} · ${esc(a.producer)}</option>`).join('')}</select><div id="artifact-body"></div></div>`; return;
  }
  panel.innerHTML = '<div class="panel-card">Loading evidence…</div>';
  try {
    let html = '';
    if(activeTab === 'code') {
      const keys = ['candidate_a','candidate_b','candidate_diff','review_a','review_b','main','test_bundle'].filter(k=>p.data[k]);
      const arts = await Promise.all(keys.map(k=>artifact(p.data[k])));
      const byKey = Object.fromEntries(keys.map((k,i)=>[k,arts[i]]));
      if(byKey.candidate_a || byKey.candidate_b) html += '<div class="columns">'+['a','b'].map(side=>`<div class="panel-card"><h3>Candidate ${side.toUpperCase()}</h3>${byKey['candidate_'+side]?artifactContent(byKey['candidate_'+side]):'<p>Not generated yet.</p>'}</div>`).join('')+'</div>';
      if(byKey.candidate_diff) html += `<div class="panel-card"><h3>Candidate A → B diff</h3>${diffBlock(byKey.candidate_diff.payload.diff)}</div>`;
      html += ['review_a','review_b'].filter(k=>byKey[k]).map(k=>`<div class="panel-card"><h3>Independent ${k.replace('_',' ')}</h3>${artifactContent(byKey[k])}</div>`).join('');
      html += ['main','test_bundle'].filter(k=>byKey[k]).map(k=>`<div class="panel-card"><h3>${k==='main'?'Canonical source':'Testing bundle (includes independent tests)'}</h3>${artifactContent(byKey[k])}</div>`).join('');
    } else if(activeTab === 'tests') {
      const keys = ['evidence_a','evidence_b','test_plan','test_action','test_result','test_summary','test_completion','test_signoff'].filter(k=>p.data[k]);
      const arts = await Promise.all(keys.map(k=>artifact(p.data[k])));
      html = arts.map(a=>`<div class="panel-card"><h3>${esc(a.kind.replaceAll('_',' '))}</h3>${artifactContent(a)}</div>`).join('');
    }
    if(generation===viewGeneration) panel.innerHTML = html || '<div class="panel-card"><h3>No evidence yet</h3><p class="muted">Run the next workflow task to produce artifacts. Earlier versions remain available under All artifacts.</p></div>';
  } catch(e) { if(generation===viewGeneration) panel.innerHTML=`<div class="error">${esc(e.message)}</div>`; }
}
function renderReview(draft) {
  const gate = snapshot.gate, p = snapshot.project;
  if(!gate) { $('#panel').innerHTML=`<div class="panel-card"><div class="eyebrow accent">${p.state==='review.closed'?'ITERATION COMPLETE':'NEXT TASK'}</div><h3>${p.state==='review.closed'?'This iteration is closed':esc(p.state)}</h3><p class="muted">${p.state==='review.closed'?'Download the accepted source or full audit above.':p.status==='failed'?'Inspect the error above, correct the cause, then choose Recover interrupted work.':'Run to the next checkpoint to generate the work that needs your review.'}</p></div>`; return; }
  const g = gate.proposal;
  const choice = g.selection_options ? `<label>Choose an option<select name="selection" aria-label="Choose an option"><option value="">Select explicitly…</option>${g.selection_options.map(o=>`<option>${esc(o)}</option>`).join('')}</select></label>` : '';
  const custom = gate.state==='dev.plan_review'?'<label>Custom approach (when selected)<textarea name="approach" rows="3"></textarea></label>':'';
  const permission = ['dev.plan_review','dev.final'].includes(gate.state)?'<label class="check"><input type="checkbox" name="allow_evaluation">I authorize the displayed bounded sandbox evaluation scope. Required for plan approval or final modification.</label>':'';
  const deploy = gate.state==='deploy.manual'?'<label>Manual deployment status<select name="status" aria-label="Manual deployment status"><option value="">Choose…</option><option value="deferred">Deferred</option><option value="deployed">Deployed manually</option></select></label><label>What you did, or why deferred<textarea name="record" rows="3"></textarea></label>':'';
  const review = gate.state==='review.feedback'?'<label>Demonstration / stakeholder notes<textarea name="demo_notes" rows="3"></textarea></label><label>Next step<select name="outcome" aria-label="Next step"><option value="">Choose…</option><option value="close">Close iteration</option><option value="iterate">Start another iteration</option></select></label><label>New requirements (for another iteration)<textarea name="new_requirements" rows="3"></textarea></label>':'';
  const extras = Object.fromEntries(Object.entries(g).filter(([k])=>!['title','state','proposal','artifacts','test_evidence','selection_options','required_input'].includes(k)));
  const explanations = snapshot.artifacts.filter(a=>a.kind==='explanation');
  $('#panel').innerHTML = `<div class="checkpoint-grid"><div><div class="panel-card"><div class="eyebrow accent">HUMAN CHECKPOINT · ${esc(g.source_requirement)}</div><h3>${esc(g.title)}</h3><p>${esc(g.proposal)}</p><h4>What to review</h4><p class="hint">${esc(g.required_input)}</p><h4>Risks</h4><ul>${g.risks.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>${g.execution_scope?`<h4>Exact execution scope</h4>${jsonBlock(g.execution_scope)}`:''}${g.policy?`<h4>Policy</h4>${jsonBlock(g.policy)}`:''}${g.measured_checks_pass!==undefined?`<h4>Current checks ${badge(g.measured_checks_pass?'pass':'fail')}</h4>`:''}<details><summary>Rationales, alternatives & routing</summary>${jsonBlock(extras)}</details><details><summary>Checkpoint identity</summary><p class="hint">${esc(gate.id)}<br>${esc(gate.digest)}</p></details></div><div class="panel-card"><h3>Proposal evidence</h3><p class="hint">Open each artifact to inspect its complete content. Source and measured tests are also available in the dedicated tabs.</p>${[...g.artifacts,...(g.test_evidence||[])].map(a=>`<details><summary>${esc(a.kind)} · ${esc(a.artifact_id.slice(-8))}</summary>${artifactContent(a)}</details>`).join('')}${explanations.length?`<h4>Answers to your questions</h4>${explanations.map(a=>`<button class="evidence-link" data-artifact="${a.id}">Explanation v${a.version}</button>`).join('')}<div id="explanation"></div>`:''}</div></div><form id="decision-form" data-gate="${gate.id}" class="panel-card decision"><div class="eyebrow accent">YOUR DECISION</div><h3>Review, then move forward</h3><label>Reviewer<input name="actor" required value="${esc(snapshot.actor)}"></label><label>Action<select name="action" aria-label="Action"><option value="approve">Approve</option><option value="modify">Request modifications</option><option value="reject">Reject</option><option value="info">Ask for information</option></select></label><label>Reason, corrections, or question<textarea name="feedback" rows="5" required placeholder="Explain what you reviewed and why, or what needs to change."></textarea></label>${choice}${custom}${permission}${deploy}${review}<label class="check"><input name="confirmed" type="checkbox" required>I reviewed this checkpoint and intend to submit this decision.</label><p id="decision-error" class="error" hidden></p><button type="submit" class="primary wide" ${snapshot.jobs[selected]?.status==='running'?'disabled':''}>Submit decision</button><p class="hint">Submitting records your decision. Use Run to next checkpoint afterward to continue.</p></form></div>`;
  if(draft) for(const [name,value] of Object.entries(draft)) { const input = $('#decision-form').elements.namedItem(name); if(input) { if(input.type==='checkbox') input.checked=true; else input.value=value; } }
  $('#decision-form').addEventListener('submit',submitDecision);
}
async function submitDecision(event) {
  event.preventDefault();
  const form=event.currentTarget, f=Object.fromEntries(new FormData(form)), gate=snapshot.gate;
  const payload={};
  if(f.action==='approve') {
    if(gate.proposal.selection_options) payload.selection=f.selection;
    if(gate.state==='dev.plan_review') { payload.approach=f.approach; payload.allow_evaluation=Boolean(f.allow_evaluation); }
    if(gate.state==='deploy.manual') Object.assign(payload,{status:f.status,record:f.record});
    if(gate.state==='review.feedback') { payload.demo_notes=f.demo_notes; if(f.outcome==='iterate') payload.new_requirements=f.new_requirements; else if(f.outcome==='close') payload.close=true; }
  }
  if(f.action==='modify' && gate.state==='dev.final') payload.allow_evaluation=Boolean(f.allow_evaluation);
  try { await action('decide',{gate:gate.id,digest:gate.digest,action:f.action,feedback:f.feedback,actor:f.actor,payload}); }
  catch(e) { $('#decision-error').hidden=false; $('#decision-error').textContent=e.message; }
}
async function action(operation, extra={}) {
  $('#error').hidden=true;
  await api('/api/action',{mode,project:selected,operation,...extra});
  renderKey=''; await refresh(true);
}
function openNew() {
  $('#new-form').reset(); $('#new-error').hidden=true;
  $('#goal-label').hidden=mode==='demo'; $('#demo-description').hidden=mode!=='demo';
  $('#new-form').elements.goal.required=mode==='live';
  if(mode==='demo') $('#new-form').elements.name.value='Unicode normalizer';
  $('#new-dialog').showModal();
}
$('#new-project').onclick=$('#empty-create').onclick=openNew;
$('#new-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;try{const f=Object.fromEntries(new FormData(form));const result=await api('/api/create',{mode,...f});selected=result.project;renderKey='';$('#new-dialog').close();await refresh(true);}catch(error){$('#new-error').hidden=false;$('#new-error').textContent=error.message;}finally{button.disabled=false;}};
$('#mode').onchange=()=>{mode=$('#mode').value;selected=null;renderKey='';viewGeneration++;snapshot=null;$('#detail').hidden=true;$('#error').hidden=true;refresh(true);};
$('#search').oninput=()=>{if(snapshot)renderProjects();};
$('#projects').onclick=e=>{const button=e.target.closest('[data-project]');if(button){selected=button.dataset.project;renderKey='';viewGeneration++;$('#detail').hidden=true;$('#error').hidden=true;refresh(true);}};
$('.tabs').onclick=e=>{const b=e.target.closest('[data-tab]');if(!b)return;activeTab=b.dataset.tab;for(const tab of document.querySelectorAll('[data-tab]'))tab.classList.toggle('active',tab===b);renderKey='';renderPanel();};
for(const op of ['run','step','recover']) $('#'+op).onclick=()=>action(op).catch(showError);
$('#rework').onclick=()=>$('#rework-dialog').showModal();
$('#rework-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;try{await action('rework',{feedback:new FormData(form).get('feedback')});$('#rework-dialog').close();form.reset();}catch(error){showError(error);}};
for(const b of document.querySelectorAll('[data-close]')) b.onclick=()=>$('#'+b.dataset.close).close();
$('#export').onclick=async()=>{try{const response=await fetch(query('/api/download',{kind:$('#export-kind').value}),{headers:{'X-HITL-Session':token}});if(!response.ok)throw new Error((await response.json()).error);const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=response.headers.get('Content-Disposition').match(/filename="([^"]+)"/)[1];a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){showError(e);}};
$('#panel').addEventListener('change',async e=>{if(e.target.id==='artifact-select'){const target=$('#artifact-body'),id=e.target.value;if(!id){target.innerHTML='';return;}try{const a=await artifact(id);if(target.isConnected&&$('#artifact-select').value===id)target.innerHTML=artifactContent(a);}catch(error){showError(error);}}});
$('#panel').addEventListener('click',async e=>{const b=e.target.closest('[data-artifact]');if(b){const target=$('#explanation');try{const a=await artifact(b.dataset.artifact);if(target?.isConnected)target.innerHTML=artifactContent(a);}catch(error){showError(error);}}});
$('#settings').onclick=async()=>{try{const config=await api('/api/config'),f=$('#settings-form');f.reset();f.elements.base_url.value=config.provider.base_url;f.elements.model.value=config.provider.model;f.elements.api_key_env.value=config.provider.api_key_env;f.elements.image.value=config.runner.image;f.elements.advanced.value=pretty(config);$('#settings-error').hidden=true;$('#settings-dialog').showModal();}catch(e){showError(e);}};
$('#settings-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,f=Object.fromEntries(new FormData(form));try{const config=JSON.parse(f.advanced);Object.assign(config.provider,{base_url:f.base_url,model:f.model,api_key_env:f.api_key_env});config.runner.image=f.image;await api('/api/config',{config,api_key:f.api_key});form.elements.api_key.value='';$('#settings-dialog').close();}catch(error){$('#settings-error').hidden=false;$('#settings-error').textContent=error.message;}};
refresh();setInterval(()=>refresh(),1500);
