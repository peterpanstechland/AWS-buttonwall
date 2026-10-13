import { EnergyField } from './energy-field.js';
const $ = (q) => document.querySelector(q);
const esc = (s = '') => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const energy = new EnergyField($('#energy-canvas'));
const debug = new URLSearchParams(location.search).has('debug');
document.body.classList.toggle('debug-ui', debug);
let lang = localStorage.getItem('wall-language') === 'en' ? 'en' : 'zh';
let services = [], missions = [], preview, snap, receivedAt = 0, pageKey = '', graphKey = '', selectedNode = null, candidate = null;
let online = false, visualPaused = false;
let actionChain = Promise.resolve();
const icons = {S3:'s3', LAMBDA:'lambda', DYNAMODB:'dynamodb', API_GATEWAY:'api-gateway', CLOUDFRONT:'cloudfront', SQS:'sqs', BEDROCK:'bedrock', AGENTCORE:'agentcore', SAGEMAKER_AI:'sagemaker', REKOGNITION:'rekognition', TRANSCRIBE:'transcribe', POLLY:'polly', CLOUDWATCH:'cloudwatch', COGNITO:'cognito'};
const say = (zh, en) => lang === 'zh' ? zh : en;
const t = (value) => value ? value[lang] || value.en || value.zh || '' : '';
const service = (key) => services.find((s) => s.key === key);
const shortName = (key) => ({AGENTCORE:'AgentCore',SAGEMAKER_AI:'SageMaker AI'}[key] || (service(key)?.official_en || '').replace(/^(Amazon |AWS )/, ''));
const endState = () => ['RESULT', 'INTERRUPTED'].includes(snap?.state);
function icon(key, extra = '') {
  return icons[key] ? `<img class="service-icon ${extra}" src="/icons/${icons[key]}.svg" alt="">` : `<span class="service-icon text-icon ${extra}">${esc(key === 'IOT_CORE' ? 'IoT' : key === 'EC2' ? 'EC2' : '?')}</span>`;
}
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').classList.remove('show'), 3500); }
function connection(value) {
  online = value;
  $('#connection').textContent = value ? say('构建引擎已连接', 'ENGINE CONNECTED') : say('连接中断 · 正在重连', 'RECONNECTING');
  $('#connection').classList.toggle('offline', !value);
}
async function json(url, options) { const r = await fetch(url, options); if (!r.ok) throw Error(`${r.status}`); return r.json(); }
function accept(data) {
  if (snap && data.boot_id===snap.boot_id && data.state_revision < snap.state_revision) return;
  if (snap?.session_id === data.session_id && data.solutions_completed > snap.solutions_completed && data.state === 'ACTIVE') toast(say('架构已接通 · 下一个挑战已开始', 'Workflow connected · Next challenge started'));
  snap = data; receivedAt = performance.now(); connection(true); draw();
}
function post(path, body = {}) {
  const run = async () => {
    try {
      const data = await json(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...body,client_action_id:crypto.randomUUID()})});
      accept(data); return data;
    } catch { connection(false); toast(say('操作未确认，请等待连接恢复。', 'Action not confirmed. Waiting for reconnection.')); return null; }
  };
  actionChain = actionChain.then(run, run);
  return actionChain;
}
async function start(mode, missionId) {
  if (await post('/api/mode/select', {mode})) await post('/api/game/start', {mission_id:missionId});
}
$('#lang').onclick = () => { lang = lang === 'zh' ? 'en' : 'zh'; localStorage.setItem('wall-language',lang); pageKey=''; draw(); fillSimulator(); };
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
let reduceMotion = localStorage.getItem('wall-reduce-motion') === 'true' || reduced.matches;
function applyMotion() { energy.setMotion({reduced:reduceMotion,paused:visualPaused||snap?.paused}); document.body.classList.toggle('reduce-motion', reduceMotion); $('#motion').setAttribute('aria-pressed',String(reduceMotion)); }
$('#motion').onclick = () => { reduceMotion = !reduceMotion; localStorage.setItem('wall-reduce-motion', String(reduceMotion)); applyMotion(); };
reduced.addEventListener('change', (e) => { reduceMotion = e.matches; applyMotion(); });
applyMotion();
$('#sim-open').onclick = () => { fillSimulator(); $('#simulator').showModal(); };
$('#sim-close').onclick = () => $('#simulator').close();
function fillSimulator() {
  $('#simulator h2').textContent = say('模拟实体按键','Simulate wall inputs');
  $('#sim-close').textContent = say('关闭 ×','Close ×');
  $('#sim-help').textContent = say('这些按钮只用于本机演示，正式现场使用实体按钮墙。','Demo controls only. Use the physical service wall at the event.');
  $('#sim-buttons').innerHTML = services.map((s) => `<button data-press="${s.id}">${s.id ? icon(s.key) : '<img class="service-icon" src="/branding/kiro.svg" alt="">'}<span>${esc(s.official_en)}<small>${esc(s.slot)} · ${esc(say(s.display_name_cn_event,s.category))}</small></span></button>`).join('') + (snap?.mode === 'FREE' ? `<p>${say('重复角色可显式添加第二个实例。','Add another instance for a repeated role.')}</p><button data-instance="LAMBDA">+ Lambda ${say('实例','instance')}</button>` : '');
  $('#sim-buttons').querySelectorAll('[data-press]').forEach((b) => b.onclick = () => post('/api/sim/press',{button_id:Number(b.dataset.press)}));
  $('#sim-buttons').querySelectorAll('[data-instance]').forEach((b) => b.onclick = () => post('/api/free/instance',{service:b.dataset.instance}));
}
function currentGraph() {
  if (snap?.mode === 'FREE' && !snap.graph) {
    const graphs = snap.candidate_graphs || {};
    candidate = snap.focused_candidate_id || Object.keys(graphs)[0];
    return graphs[candidate] || null;
  }
  return snap?.graph;
}
function stageMarkup() {
  return `<section class="architecture-stage" aria-label="${say('架构构建画布','Architecture canvas')}"><div class="stage-topline"><span class="eyebrow">SIG.02 / SIGNAL BRIDGE <i>/</i> <span id="stage-state"></span></span><div class="legend"><span><i class="legend-dot live"></i>${say('已贯通','Connected')}</span><span><i class="legend-dot ready"></i>${say('待接通信号','Next signal')}</span></div></div><div id="graph-wrap"></div><div class="stage-bottomline"><span id="graph-caption"></span><span id="graph-progress"></span></div></section>`;
}
function draw() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.title = say('Bridge with Signal · 架构构建站','Bridge with Signal · Architecture Station');
  $('.brand').setAttribute('aria-label',document.title);
  $('.brand-sub').textContent = say('COMMUNITY DAY / 架构构建站','COMMUNITY DAY / ARCHITECTURE STATION');
  $('#lang').setAttribute('aria-label',say('切换到 English','Switch to 中文'));
  $('#lang').title = say('切换到 English','Switch to 中文');
  $('#lang [lang="zh-CN"]').classList.toggle('current',lang==='zh');
  $('#lang [lang="en"]').classList.toggle('current',lang==='en');
  connection(online);
  if (!snap) {
    $('.loading').textContent = say('正在连接构建引擎…','Connecting to the build engine…');
    return;
  }
  $('#sim-open').hidden = !snap.demo || !debug; $('#demo-badge').hidden = !snap.demo;
  $('#sim-open').textContent = say('模拟输入','Demo input');
  $('#motion').setAttribute('aria-label',say('减少动态效果','Reduce motion'));
  $('#footnote').textContent = say('本地教学模拟 · 不创建云资源','LOCAL TEACHING SIMULATION · NO CLOUD RESOURCES');
  $('#footer-status').textContent = snap.demo ? 'SIMULATION ONLINE' : 'LOCAL SYSTEM';
  const kind = ['IDLE','MODE_LOBBY','MISSION_SELECT','OPERATOR'].includes(snap.state) ? snap.state : 'BUILD';
  document.body.classList.toggle('attract-mode',kind==='IDLE');
  const key = `${kind}/${lang}/${snap.session_id || ''}/${kind==='MODE_LOBBY'?snap.mode:''}/${kind==='MISSION_SELECT'?snap.menu_mission_id:''}`;
  if (key !== pageKey) {
    // Keep the same physical-input control and its listeners when the page changes.
    // Park it outside the screen before replacing any markup containing it.
    if($('#screen').contains(kiro)) $('#kiro-dock-slot').append(kiro);
    pageKey = key; graphKey = ''; selectedNode = null;
    $('#screen').className = kind === 'BUILD' ? 'build-screen' : 'intro-screen';
    if (kind === 'IDLE') drawAttract();
    else if (kind === 'MODE_LOBBY' || kind === 'MISSION_SELECT') drawLobby();
    else if (kind === 'OPERATOR') $('#screen').innerHTML = `<h1>${say('设备需要检查','Device needs attention')}</h1><p>${esc(snap.notice)}</p>`;
    else drawBuild();
  }
  if ($('#back')) $('#back').onclick = () => post('/api/game/leave');
  if (kind === 'BUILD') updateBuild();
  else energy.attach(null,null,kind,true);
  const kiroSlot=kind==='IDLE'?$('#hero-kiro-slot'):$('#kiro-dock-slot');
  if(kiro.parentElement!==kiroSlot)kiroSlot.append(kiro);
  kiro.classList.toggle('kiro-hero',kind==='IDLE');
  kiro.setAttribute('aria-label',kind==='IDLE'?say('开始构建（Kiro）','Start building with Kiro'):say('Kiro 按键','Kiro button'));
  $('#kiro-start-title').textContent=say('开始构建','Start building');
  updateKiroGuide();
  energy.setMotion({reduced:reduceMotion,paused:visualPaused||snap.paused||['COUNTDOWN','SETTLING','INTERRUPTED'].includes(snap.state)});
}
function drawAttract() {
  $('#screen').innerHTML = `<section class="signal-attract"><div class="signal-title"><p class="eyebrow">SIGNAL HUNT / ARCHITECTURE STATION</p><h1><span>BRIDGE</span><small>WITH</small><span>SIGNAL</span></h1><h2>${say('接通能力，让信号过桥。','Build a path for your signal.')}</h2><p>${say('拍下云服务，搭建你的架构。每接通一个节点，信号就向前一步。','Hit cloud services to build your architecture. Every connected capability carries the signal forward.')}</p><div class="hero-start"><div id="hero-kiro-slot"></div><p class="hero-start-help">${snap.sim_input?say('拍下 Kiro · 也可点击或按空格开始','PRESS KIRO · CLICK OR PRESS SPACE TO BEGIN'):say('拍下墙上的 Kiro 开始键','PRESS THE PHYSICAL KIRO BUTTON TO BEGIN')}</p></div></div><div class="bridge-poster" aria-hidden="true"><div class="bridge-poster-head">SIG.01 // BUILD A CONNECTION</div><svg viewBox="0 0 620 405"><defs><pattern id="bridge-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" fill="none" stroke="#141414" stroke-opacity=".07"/></pattern></defs><rect width="620" height="405" fill="url(#bridge-grid)"/><path d="M0 353Q155 304 310 355T620 347V405H0Z" fill="#2b5ce6" stroke="#141414" stroke-width="4"/><g fill="#ffd900" stroke="#141414" stroke-width="5"><path d="M130 299V117H171V299H151V143H149V299Z"/><path d="M449 299V117H490V299H470V143H468V299Z"/><path d="M43 299H577V325H43Z"/></g><g fill="none" stroke="#141414" stroke-width="4" stroke-linecap="round"><path d="M25 274Q72 250 150 132Q310 376 470 132Q548 250 595 274"/><path d="M92 218V299M211 210V299M272 250V299M348 250V299M409 210V299M530 218V299"/></g><path d="M25 274Q72 250 150 132Q310 376 470 132Q548 250 595 274" class="bridge-signal" fill="none" stroke="#6c3fd4" stroke-width="7" stroke-linecap="round"/><g fill="#6c3fd4" stroke="#141414" stroke-width="4"><circle cx="150" cy="103" r="12"/><circle cx="470" cy="103" r="12"/><circle cx="310" cy="254" r="12"/></g><path d="M231 68Q251 35 271 68T311 68T351 68T391 68" fill="none" stroke="#6c3fd4" stroke-width="6" stroke-linecap="round"/><g font-family="monospace" font-weight="700" font-size="12" fill="#141414"><text x="47" y="38">CONNECT A CAPABILITY.</text><text x="47" y="56">CARRY THE SIGNAL.</text></g></svg><div class="bridge-poster-foot">${say('一段能力，一次连接。由你完成这座桥。','ONE CAPABILITY. ONE CONNECTION. BUILT BY YOU.')}</div></div></section>`;
}
function drawLobby() {
  const options=[['GUIDED','引导构建','Guided build','跟随能力线索，让信号通过完整的架构。','Follow capability clues. Connect the complete workflow.'],['RUSH60_RANKED','60 秒竞速','Builder rush','在 60 秒内接通信号桥。拍错或超时，架构垮塌。','Every step matters. A wrong or missed hit collapses the flow.'],['FREE','自由探索','Free exploration','组合服务，发现它们能构建的方案。','Combine services. Discover the workflows they can create.']];
  if(snap.state==='MISSION_SELECT') {
    const eligible=missions.filter(m=>m.ranked), current=eligible.find(m=>m.id===snap.menu_mission_id)||eligible[0];
    const index=eligible.indexOf(current);
    $('#screen').innerHTML=`<section class="single-choice"><div class="choice-copy"><p class="eyebrow">GUIDED BUILD / ${say('选择场景','CHOOSE A SCENARIO')}</p><h1>${esc(t(current.title))}</h1><p>${esc(t(current.story))}</p><div class="scenario-dots">${eligible.map((m,i)=>`<span class="${m.id===current.id?'focused':''}">${String(i+1).padStart(2,'0')}</span>`).join('')}</div></div><div class="choice-number"><span>MISSION</span><strong>${String(index+1).padStart(2,'0')}</strong><small>/ 08</small></div></section>`;
  } else {
    const current=options.find(m=>m[0]===snap.mode)||options[0];
    $('#screen').innerHTML=`<section class="single-choice"><div class="choice-copy"><p class="eyebrow">CHOOSE YOUR SIGNAL PATH</p><h1>${say(current[1],current[2])}</h1><p>${say(current[3],current[4])}</p><p class="choice-rule">${say('引导与竞速：单步 10 秒 · 接错即垮塌','GUIDED & RUSH / 10s PER STEP / WRONG HIT COLLAPSES')}</p></div><div class="mode-track" role="list" aria-label="${say('游戏模式','Game modes')}">${options.map((m,i)=>`<div role="listitem" class="${m[0]===current[0]?'focused':''}"><span>0${i+1}</span><strong>${say(m[1],m[2])}</strong><i>${m[0]===current[0]?'●':'○'}</i></div>`).join('')}</div></section>`;
  }
}
function drawBuild() {
  $('#screen').innerHTML=`<section class="mission-header"><div><div class="mission-eyebrow"><span class="eyebrow" id="mode-name"></span></div><h1 id="mission-title"></h1><p id="mission-story"></p></div><div class="session-metrics"><div><span>${say('已贯通','BRIDGES')}</span><b id="builds">00</b></div><div><span>${say('得分','SCORE')}</span><b id="score">0000</b></div><div id="total-time"><span>${say('整局剩余','SESSION')}</span><b id="round-clock"></b></div></div></section><div class="workspace">${stageMarkup()}<aside class="build-director"><div id="director-content" aria-live="polite"></div><div id="node-detail"></div></aside></div><section id="workflow-bar" hidden></section><section id="free-actions"></section><div id="countdown" class="countdown" hidden></div>`;
}
function updateBuild() {
  const graph=currentGraph();
  $('#mode-name').textContent = 'SIG.01 / ' + (snap.mode === 'FREE' ? say('自由探索','FREE BUILD') : snap.mode === 'GUIDED' ? say('引导构建','GUIDED BUILD') : say('架构竞速','SIGNAL RUSH'));
  $('#mission-title').textContent = snap.mission ? t(snap.mission.title) : graph ? t(graph.title) : say('你的灵感，从这里接通。','Connect your next idea.');
  $('#mission-story').textContent = snap.mission ? t(snap.mission.story) : say('拍下实体服务键选择能力，再分析它们能构成的架构。','Select capabilities on the wall, then analyze their workflows.');
  $('#builds').textContent=String(snap.solutions_completed).padStart(2,'0');
  $('#score').textContent=String(snap.score).padStart(4,'0');
  $('#total-time').hidden=snap.remaining_ms==null;
  if (graph) mountGraph(graph);
  else drawFreeCollection();
  const failure=snap.failure;
  const signature=JSON.stringify([snap.state,snap.paused,failure,graph?.id,graph?.connected_count,selectedNode,lang,snap.notice,snap.selected,snap.candidates,snap.forfeit_pending]);
  if ($('#director-content').dataset.signature!==signature) {
    $('#director-content').dataset.signature=signature;
    let html='';
    if(snap.forfeit_pending && !endState()) html=`<div class="rail-status warning"><span class="eyebrow">LEAVE THIS RUN?</span><h2>${say('结束本局？','End this run?')}</h2></div><p>${say('双击 Kiro 确认 · 单击取消；计时继续。','Double press to confirm · single to cancel. The clock keeps running.')}</p>`;
    else if(snap.state==='INTERRUPTED') html=`<div class="rail-status warning"><span class="eyebrow">SESSION INTERRUPTED</span><h2>${say('本局已中断','Run interrupted')}</h2></div><p>${say('本局不进入正式排名。','This run is not ranked.')}</p>`;
    else if(failure) {
      const reasons={WRONG_SERVICE:say('接错能力，链路中断','Wrong capability. Flow broken.'),STEP_TIMEOUT:say('单步超时，关键能力未接通','Step timed out. A capability is missing.'),ROUND_TIMEOUT:say('整局时间到，架构未完成','Time up. The architecture is incomplete.')};
      const next=graph?.nodes.find(n=>failure.missing_nodes.includes(n.node_id));
      html=`<div class="rail-status failure-label"><span class="eyebrow">SIGNAL LOST / BRIDGE COLLAPSED</span><h2>${say('架构垮塌','Architecture collapsed')}</h2></div><div class="rail-reason"><p>${reasons[failure.reason]}</p><strong>${say('断点：','Break: ')}${esc(t(next?.role))}</strong></div>`;
    } else if(graph?.status==='complete'&&snap.mode==='FREE'&&!endState()) html=`<div class="rail-status success-label"><span class="eyebrow">READY TO CONNECT</span><h2>${say('方案可接通','Ready to connect')}</h2></div><p>${say('双击 Kiro，确认这套架构。','Double press Kiro to confirm this workflow.')}</p>`;
    else if(graph?.status==='complete') html=`<div class="rail-status success-label"><span class="eyebrow">SIGNAL CONNECTED / BRIDGE COMPLETE</span><h2>${say('信号桥已贯通','The signal is through.')}</h2></div><p>${say('所有必要能力已接通','All required capabilities connected')} <span class="completion-count">${graph.connected_count}/${graph.required_count}</span></p>`;
    else if(snap.state==='SETTLING') html=`<div class="rail-status"><span class="eyebrow">VERIFYING INPUTS</span><h2>${say('正在结算…','Settling…')}</h2></div><p>${say('正在确认截止前的最后一次拍击。','Verifying the last hit before the deadline.')}</p>`;
    else if(snap.mode==='FREE') html=`<div class="rail-status"><span class="eyebrow">${snap.free_review?'REVIEW WORKFLOW':'COMPOSE YOUR IDEA'}</span><h2>${snap.free_review?esc(t(graph?.title)):say('拍下服务，组合能力','Hit a service. Add a capability.')}</h2></div><p>${snap.free_review?say('黄色节点：仍需补齐的能力','Yellow nodes: missing capabilities'):say('Lambda 可重复拍两次 · 双击 Kiro 撤销','Hit Lambda twice for two roles · double Kiro to undo')}</p>`;
    else html=`<div class="rail-status"><span class="eyebrow">${snap.paused?'SIGNAL PAUSED':'SIG.03 / NEXT CAPABILITY'}</span><h2>${snap.paused?say('构建已暂停','Build paused'):esc(t(snap.role_hint))}</h2></div><div class="rail-timing"><div class="step-track"><div id="step-fill"></div></div><span id="step-clock" class="step-clock"></span></div><span class="rail-streak">×${snap.streak} <small>COMBO</small></span>`;
    $('#director-content').innerHTML=html;
  }
  updateDetail(graph);
  updateFreeActions();
  $('#countdown').hidden=!['COUNTDOWN','PREPARE'].includes(snap.state);
  $('#countdown').innerHTML=`<span>${say('准备接通你的架构','GET READY TO CONNECT')}</span><b>${snap.state==='PREPARE'?say('松开按键','RELEASE KEYS'):esc(snap.notice)}</b>`;
  updateClocks();
}
function drawFreeCollection() {
  const signature=JSON.stringify(snap.selected);
  if(graphKey===`free/${signature}`) return;
  graphKey=`free/${signature}`;
  energy.attach(null,null,'free-edit',false);
  const entries=Object.entries(snap.selected||{});
  $('#graph-wrap').innerHTML=`<div class="free-collection"><span class="eyebrow">CAPABILITY WORKSPACE</span><h2>${say('先选择能力，再发现架构。','Choose capabilities. Discover a workflow.')}</h2>${entries.length?`<div class="selected-services">${entries.map(([key,count])=>`<div>${icon(key)}<strong>${esc(shortName(key))}</strong><span>×${count}</span></div>`).join('')}</div>`:`<p>${say('拍下墙上的服务按钮，你的构建就从这里开始。','Hit a service on the wall to start building here.')}</p><div class="empty-orbit" aria-hidden="true"><span>+</span></div>`}</div>`;
  $('#stage-state').textContent=say('自由探索','EXPLORING'); $('#graph-progress').textContent=''; $('#graph-caption').textContent=say('服务集合尚不代表已接通的架构','A service collection is not yet a connected workflow');
}
function updateFreeActions() {
  const target=$('#free-actions');
  if(snap.mode!=='FREE'||endState()){target.innerHTML='';return;}
  const signature=JSON.stringify([snap.candidates,snap.focused_candidate_id,snap.notice,lang]);
  if(target.dataset.signature===signature)return;target.dataset.signature=signature;
  target.innerHTML=`${snap.notice==='UNSUPPORTED'?`<p class="free-note">${say('暂未找到匹配方案，继续调整服务组合。','No matching local workflow yet. Adjust your selection.')}</p>`:''}<div class="candidate-list">${(snap.candidates||[]).map(c=>`<div class="candidate ${c.mission_id===snap.focused_candidate_id?'chosen':''}"><strong>${esc(t(c.title))}</strong><span>${c.matched_required}/${c.total_required}</span></div>`).join('')}</div>`;
}
function nodeBody(n) {
  return `<div class="node-heading">${icon(n.service)}<span class="node-number">${n.required ? 'CORE' : 'OPTIONAL'}</span></div><strong>${n.service?esc(shortName(n.service)):say('待接入能力','Unknown service')}</strong><span class="node-role">${esc(t(n.role))}</span><span class="node-status">${snap?.failure?say('信号中断','SIGNAL LOST'):n.state==='live'?say('信号已接通','CONNECTED'):n.state==='ready'?(n.required?say('等待激活','AWAITING INPUT'):say('可选能力','OPTIONAL')):n.state==='selected'?say('等待上游','UPSTREAM MISSING'):say('尚未接通','NOT CONNECTED')}</span>`;
}
function geometry(graph) {
  const result=new Map(graph.nodes.map(n=>[n.node_id,{x:n.x,y:n.y,w:168,h:120}]));
  result.set('input',{x:12,y:245,w:110,h:64}); result.set('output',{x:1150,y:245,w:115,h:64}); return result;
}
function pathFor(edge,boxes) {
  const s=boxes.get(edge.source),tgt=boxes.get(edge.target);
  if(!s||!tgt) return '';
  if(edge.kind==='observe' || edge.kind==='control' || edge.kind==='side') {
    const sx=s.x+s.w/2,sy=s.y+s.h,tx=tgt.x+tgt.w/2,ty=tgt.y;
    // Route long observability branches below the main lane, away from service boxes.
    const bend=Math.max(sy+25,ty-25);
    return `M${sx},${sy} C${sx},${bend} ${tx},${bend} ${tx},${ty}`;
  }
  const sx=s.x+s.w,sy=s.y+s.h/2,tx=tgt.x,ty=tgt.y+tgt.h/2;
  const dx=Math.max(18,(tx-sx)/2);
  return `M${sx},${sy} C${sx+dx},${sy} ${tx-dx},${ty} ${tx},${ty}`;
}
function mountGraph(graph, decorative=false) {
  if(!graph||!$('#graph-wrap')) return;
  const key=`${graph.id}/${lang}/${decorative}/${snap?.round_id||''}`;
  if(key!==graphKey) {
    graphKey=key; selectedNode=null;
    const boxes=geometry(graph);
    const top=Math.min(210, ...graph.nodes.map(n=>n.y-70));
    const bottom=Math.max(350, ...graph.nodes.map(n=>n.y+190));
    $('#graph-wrap').innerHTML=`<svg id="architecture" viewBox="0 ${top} 1280 ${bottom-top}" preserveAspectRatio="xMidYMid meet" role="group" aria-label="${esc(t(graph.title))}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 1L8 5L0 9" fill="none" stroke="context-stroke" stroke-width="1.4"/></marker></defs><rect x="145" y="${top+18}" width="978" height="${bottom-top-36}" rx="24" class="cloud-boundary"/><text x="168" y="${top+43}" class="boundary-label">${say('能力工作流 / 教学模拟','CAPABILITY WORKFLOW / SIMULATION')}</text>${graph.edges.map(edge=>`<g class="flow-edge ${edge.kind}" data-edge="${edge.id}"><path class="edge-base" d="${pathFor(edge,boxes)}" marker-end="url(#arrow)"/><path class="edge-stream" d="${pathFor(edge,boxes)}"/><text class="edge-label"><textPath href="#label-${edge.id}" startOffset="50%" text-anchor="middle">${esc(t(edge.label))}</textPath></text><path id="label-${edge.id}" d="${pathFor(edge,boxes)}" fill="none" stroke="none"/></g>`).join('')}<g class="io-node source"><rect x="12" y="245" width="110" height="64" rx="12"/><text x="67" y="269" class="io-label">INPUT</text><text x="67" y="291">${esc(t(graph.io.input))}</text></g><g class="io-node sink"><rect x="1150" y="245" width="115" height="64" rx="12"/><text x="1207" y="269" class="io-label">OUTPUT</text><text x="1207" y="291">${esc(t(graph.io.output))}</text></g>${graph.nodes.map((n,i)=>`<g class="node-position" transform="translate(${n.x} ${n.y})"><foreignObject width="168" height="128" style="overflow:visible"><${debug?'button':'div'} xmlns="http://www.w3.org/1999/xhtml" class="graph-node" data-node="${n.node_id}" style="--fall-delay:${i*90}ms;--tilt:${i%2?6:-5}deg" ${decorative||!debug?'tabindex="-1"':''}>${nodeBody(n)}</${debug?'button':'div'}></foreignObject></g>`).join('')}</svg>`;
    $('#graph-wrap').querySelectorAll('[data-node]').forEach(b=>b.onclick=()=>{if(!decorative&&debug){selectedNode=b.dataset.node;updateDetail(currentGraph());}});
  }
  const svg=$('#architecture');
  energy.attach(svg,graph,`${snap?.round_id||'preview'}/${graph.id}`,decorative);
  svg.classList.toggle('collapsed',graph.status==='collapsed');
  svg.classList.toggle('complete',graph.status==='complete');
  svg.classList.toggle('frozen',snap?.state==='INTERRUPTED'||snap?.paused||(!decorative && ['COUNTDOWN','PREPARE','SETTLING'].includes(snap?.state)));
  for(const n of graph.nodes) {
    const button=svg.querySelector(`[data-node="${n.node_id}"]`);
    button.className=`graph-node ${n.state} ${!n.required?'optional':''} ${snap?.failure?.missing_nodes.includes(n.node_id)?'fault':''}`;
    const body=nodeBody(n); if(button.innerHTML!==body) button.innerHTML=body;
    if(debug) button.setAttribute('aria-pressed',String(selectedNode===n.node_id));
    button.setAttribute('aria-label',`${t(n.role)} · ${n.service?shortName(n.service):say('未知服务','Unknown service')} · ${n.state}`);
  }
  for(const edge of graph.edges) svg.querySelector(`[data-edge="${edge.id}"]`).classList.toggle('live',edge.state==='live');
  svg.querySelector('.sink').classList.toggle('live',graph.status==='complete');
  if(!decorative) {
    $('#stage-state').textContent=graph.status==='collapsed'?'COLLAPSED':graph.status==='complete'?'FLOWING':'UNDER CONSTRUCTION';
    $('#graph-progress').textContent=`${graph.connected_count} / ${graph.required_count} ${say('必要能力已接通','REQUIRED CONNECTED')}`;
    $('#graph-caption').textContent=say('实线：能力交接 · 虚线：准备 / 辅助关系','SOLID: HANDOFF · DASHED: PREPARATION / SUPPORT');
    $('.architecture-stage').classList.toggle('has-failure',graph.status==='collapsed');
  }
}
function updateDetail(graph) {
  const box=$('#node-detail'); if(!box||!debug) return;
  const n=graph?.nodes.find(n=>n.node_id===selectedNode);
  const detailSignature=JSON.stringify([graph?.id, selectedNode, n?.service, lang]);
  if(box.dataset.signature===detailSignature) return;
  box.dataset.signature=detailSignature;
  if(!n) {box.innerHTML=`<p class="detail-prompt">${say('点击图中节点，查看它的职责。','Select a node to explore its role.')}</p>`;return;}
  box.innerHTML=`<div class="detail-heading"><span class="eyebrow">NODE INSPECTOR</span><button id="close-detail" aria-label="${say('关闭节点详情','Close node details')}">×</button></div><h3>${esc(t(n.role))}</h3><p>${n.service?esc(service(n.service)?.official_en):say('竞速中请根据能力线索判断服务。','Identify this service from its capability clue.')}</p><p>${n.required?say('必要能力 · 缺失时工作流无法完整运行。','Required capability. The workflow needs this role.'):say('辅助能力 · 提供额外能力，不阻断核心链路。','Optional capability. It does not block the core workflow.')}</p><small>${esc(t(graph.scope))}</small>`;
  $('#close-detail').onclick=()=>{selectedNode=null;updateDetail(graph);};
}
function updateClocks() {
  if(!snap) return;
  const elapsed = online && !snap.paused && snap.state==='ACTIVE' ? performance.now()-receivedAt : 0;
  const remaining = (v)=>Math.max(0, v-elapsed)/1000;
  if($('#round-clock')&&snap.remaining_ms!=null) $('#round-clock').innerHTML=`${remaining(snap.remaining_ms).toFixed(1)}<small>s</small>`;
  if($('#step-clock')&&snap.step_remaining_ms!=null) {
    const value=remaining(snap.step_remaining_ms);
    $('#step-clock').textContent=`${value.toFixed(1)}s`;
    $('#step-clock').classList.toggle('urgent',value<=3);
    $('#step-fill').style.transform=`scaleX(${Math.min(1,value*1000/snap.step_duration_ms)})`;
    $('#step-fill').classList.toggle('urgent',value<=3);
  }
}
let kiroDown=false,kiroDownAt=0,kiroEdges=Promise.resolve();
function kiroLevel(down) {
  if(!snap?.sim_input||kiroDown===down)return;
  kiroDown=down;kiroDownAt=down?performance.now():0;
  $('#kiro-control').classList.toggle('pressed',down);
  // Preserve both edges of fast mouse/assistive clicks across MCU debounce.
  // Gesture classification remains in the MCU, including its double-click window.
  kiroEdges=kiroEdges.then(async()=>{
    await post('/api/sim/level',{button_id:0,down});
    await new Promise(resolve=>setTimeout(resolve,45));
  });
}
const kiro=$('#kiro-control');
let kiroKey=null;
kiro.addEventListener('pointerdown',e=>{if(!e.isPrimary||e.button!==0)return;e.preventDefault();kiro.focus({preventScroll:true});kiro.setPointerCapture(e.pointerId);kiroLevel(true);});
for(const name of ['pointerup','pointercancel','lostpointercapture'])kiro.addEventListener(name,()=>kiroLevel(false));
document.addEventListener('keydown',e=>{
  if(e.key==='`'&&snap?.demo){$('#simulator').showModal();fillSimulator();return;}
  const control=e.target.closest?.('button,a,input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="button"]');
  if((e.code==='Space'||e.code==='Enter')&&!e.repeat&&!kiroKey&&!$('#simulator').open&&(!control||control===kiro)){
    e.preventDefault();kiroKey=e.code;kiroLevel(true);
  }
});
document.addEventListener('keyup',e=>{if(e.code===kiroKey){e.preventDefault();kiroKey=null;kiroLevel(false);}});
window.addEventListener('blur',()=>{kiroKey=null;kiroLevel(false);});
document.addEventListener('visibilitychange',()=>{if(document.hidden){kiroKey=null;kiroLevel(false);}});
setInterval(()=>{const progress=kiroDown?Math.min(1,(performance.now()-kiroDownAt)/2000):0;kiro.style.setProperty('--hold',`${progress*360}deg`);},50);
function updateKiroGuide() {
  let primary='',secondary='';
  if(snap.state==='IDLE'){primary=say('16 项云能力 · 一座信号桥','16 CLOUD SERVICES / ONE SIGNAL BRIDGE');secondary=say('由你搭建，由你接通。','BUILT AND CONNECTED BY YOU.');}
  else if(['MODE_LOBBY','MISSION_SELECT'].includes(snap.state)){primary=say('单击切换 · 双击确认','PRESS TO BROWSE · DOUBLE TO CONFIRM');secondary=say('长按 2 秒返回','HOLD 2s TO GO BACK');}
  else if(endState()){primary=snap.mode==='GUIDED'&&!snap.failure&&snap.final_state==='VALID'?say('单击下一关 · 双击选模式','PRESS FOR NEXT · DOUBLE FOR MODES'):say('单击重试 · 双击选模式','PRESS TO RETRY · DOUBLE FOR MODES');secondary=say('长按回到开始','HOLD TO RETURN TO START');}
  else if(snap.forfeit_pending){primary=say('双击结束 · 单击取消','DOUBLE TO END · PRESS TO CANCEL');secondary=say('比赛计时继续','THE CLOCK KEEPS RUNNING');}
  else if(snap.mode==='FREE'){
    const c=snap.candidates?.find(c=>c.mission_id===snap.focused_candidate_id);
    primary=snap.free_review?(c?.status==='VALID_COMPLETE'?say('单击换方案 · 双击确认','PRESS FOR NEXT · DOUBLE TO CONFIRM'):say('单击换方案 · 长按继续编辑','PRESS FOR NEXT · HOLD TO EDIT')):say('单击分析 · 双击撤销','PRESS TO ANALYZE · DOUBLE TO UNDO');
    secondary=snap.free_review?say('长按返回编辑','HOLD TO EDIT'):say('长按返回模式选择','HOLD FOR MODE SELECT');
  } else if(snap.mode==='GUIDED'&&snap.state==='ACTIVE'){primary=snap.paused?say('单击继续构建','PRESS TO RESUME'):say('拍服务键构建 · Kiro 单击暂停','HIT SERVICES TO BUILD · KIRO TO PAUSE');secondary=say('长按返回模式选择','HOLD FOR MODE SELECT');}
  else {primary=say('拍下对应服务，接通架构','HIT THE RIGHT SERVICE TO CONNECT');secondary=say('长按 Kiro 结束本局','HOLD KIRO TO END THE RUN');}
  const html=`<strong>${primary}</strong><span>${secondary}</span>`;
  if($('#kiro-guide').innerHTML!==html)$('#kiro-guide').innerHTML=html;
  kiro.disabled=!snap.sim_input;
}
let socket;
function connectSocket() {
  socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/events`);
  socket.onmessage=event=>{try{const data=JSON.parse(event.data);if(data.snapshot)accept(data.snapshot);}catch{}};
  socket.onclose=()=>setTimeout(connectSocket,2000);
  socket.onerror=()=>socket.close();
}
async function poll() {try{accept(await json('/api/snapshot'));}catch{connection(false);}finally{setTimeout(poll,500);}}
async function boot() {
  try {
    [services,missions,preview]=await Promise.all([json('/api/content/services'),json('/api/content/missions'),json('/api/preview')]);
    accept(await json('/api/snapshot')); fillSimulator(); connectSocket(); poll();
  } catch {$('#screen').innerHTML=`<div class="loading">${say('构建引擎暂未连接，正在重试…','Waiting for the build engine…')}</div>`;connection(false);setTimeout(boot,2000);}
}
setInterval(updateClocks,100);
draw();
boot();
