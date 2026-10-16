import { EnergyField } from './energy-field.js';
import { renderAttractDemo, mountAttractDemo } from './attract-demo.js';
import { guidanceFor, guidanceMarkup, VoiceGuide } from './guidance.js';
import { navigationMarkup, settingsMarkup } from './button-navigation.js';
const $ = (q) => document.querySelector(q);
const esc = (s = '') => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const energy = new EnergyField($('#energy-canvas'));
const debug = new URLSearchParams(location.search).has('debug');
document.body.classList.toggle('kiosk-performance',new URLSearchParams(location.search).has('kiosk'));
let attractController = null;
document.body.classList.toggle('debug-ui', debug);
let lang = localStorage.getItem('wall-language') === 'en' ? 'en' : 'zh';
const voiceGuide = new VoiceGuide({onChange: renderVoiceControls});
let currentGuide = null;
let settingsRevision = null, replaySequence = null;
let services = [], missions = [], preview, snap, receivedAt = 0, pageKey = '', graphKey = '', selectedNode = null, candidate = null;
let online = false, visualPaused = false;
let actionChain = Promise.resolve();
const icons = {EC2:'ec2',IOT_CORE:'iot-core',S3:'s3', LAMBDA:'lambda', DYNAMODB:'dynamodb', API_GATEWAY:'api-gateway', CLOUDFRONT:'cloudfront', SQS:'sqs', BEDROCK:'bedrock', AGENTCORE:'agentcore', SAGEMAKER_AI:'sagemaker', REKOGNITION:'rekognition', TRANSCRIBE:'transcribe', POLLY:'polly', CLOUDWATCH:'cloudwatch', COGNITO:'cognito'};
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
  const changed = online !== value;
  online = value;
  $('#connection').textContent = value ? say('构建引擎已连接', 'ENGINE CONNECTED') : say('连接中断 · 正在重连', 'RECONNECTING');
  $('#connection').classList.toggle('offline', !value);
  if(changed && snap) updateKiroGuide();
}
async function json(url, options) { const r = await fetch(url, options); const data=await r.json(); if (!r.ok) {const error=Error(`${r.status}`); error.status=r.status; error.data=data; throw error;} return data; }
function actionId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // HTTP access over the LAN lacks randomUUID, but still supports getRandomValues.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
function accept(data) {
  if (snap && data.boot_id===snap.boot_id && data.state_revision < snap.state_revision) return;
  if (snap?.session_id === data.session_id && data.solutions_completed > snap.solutions_completed && data.state === 'ACTIVE') toast(say('架构已接通 · 下一个挑战已开始', 'Workflow connected · Next challenge started'));
  snap = data;
  const settings = data.ui_settings;
  let replay = false;
  if (settings && settings.revision !== settingsRevision) {
    lang = settings.language === 'en' ? 'en' : 'zh';
    localStorage.setItem('wall-language', lang);
    voiceGuide.setEnabled(settings.voice_enabled);
    voiceGuide.setVolume(settings.volume);
    reduceMotion = Boolean(settings.reduced_motion);
    applyMotion();
    settingsRevision = settings.revision;
  }
  if(settings){replay = replaySequence !== null && settings.replay_seq !== replaySequence; replaySequence = settings.replay_seq;}
  receivedAt = performance.now(); connection(true); draw();
  if(replay) void voiceGuide.replay();
}
function post(path, body = {}) {
  const run = async () => {
    try {
      const data = await json(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...body,client_action_id:actionId()})});
      accept(data); return data;
    } catch(error) { if(error.status===409){if(error.data?.snapshot)accept(error.data.snapshot);toast(say('比赛进行中，请按屏幕提示结束本局。','Finish this run using the on-screen instructions.'));}else{connection(false);toast(say('操作未确认，请等待连接恢复。', 'Action not confirmed. Waiting for reconnection.'));} return null; }
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
function applyMotion() { energy.setMotion({reduced:reduceMotion,paused:visualPaused||snap?.paused}); attractController?.setReducedMotion(reduceMotion); document.body.classList.toggle('reduce-motion', reduceMotion); $('#motion').setAttribute('aria-pressed',String(reduceMotion)); }
$('#motion').onclick = () => { reduceMotion = !reduceMotion; localStorage.setItem('wall-reduce-motion', String(reduceMotion)); applyMotion(); };
reduced.addEventListener('change', (e) => { reduceMotion = e.matches; applyMotion(); });
applyMotion();
$('#sim-open').onclick = () => { if(!snap?.sim_input)return; fillSimulator(); if(!$('#simulator').open)$('#simulator').show(); };
$('#sim-close').onclick = () => $('#simulator').close();
$('#voice-toggle').onclick = () => voiceGuide.toggle();
$('#voice-replay').onclick = () => { void voiceGuide.replay(); };
$('#home').onclick = () => post('/api/game/home');
document.addEventListener('pointerdown',()=>{void voiceGuide.unlock();},{passive:true});
document.addEventListener('keydown',()=>{void voiceGuide.unlock();});
function fillSimulator() {
  $('#simulator h2').textContent = say('鼠标测试按键','Mouse test buttons');
  $('#sim-close').textContent = say('关闭 ×','Close ×');
  $('#sim-help').textContent = say('点击服务键模拟拍击；页面底部 Kiro 支持单击、双击和按住 2 秒。','Click a service to simulate a hit. Kiro on the page supports click, double click and holding for 2 seconds.');
  const ordered=(snap?.grid?.flat()||[]).map(slot=>services.find(s=>s.slot===slot)).filter(Boolean);
  $('#sim-buttons').innerHTML = ordered.map(s=>`<button type="button" data-press="${s.id}">${icon(s.key)}<span>${esc(shortName(s.key))}<small>${esc(s.slot)}</small></span></button>`).join('');
  $('#sim-buttons').querySelectorAll('[data-press]').forEach((b) => b.onclick = () => post('/api/sim/press',{button_id:Number(b.dataset.press)}));
}
document.addEventListener('click', event => {
  const button=event.target.closest('[data-wall-button]');
  if(button && snap?.sim_input && online)void post('/api/sim/press',{button_id:Number(button.dataset.wallButton)});
});
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
  $('#sim-open').hidden = !snap.sim_input; $('#demo-badge').hidden = !snap.demo;
  if(snap.physical_link) {
    const link=snap.physical_link;
    $('#connection').textContent=!link.online?say('按键设备未连接','BUTTON DEVICE OFFLINE'):!link.ready?say('请先松开所有按键','RELEASE ALL BUTTONS'):say('实体按键已连接 · 体验模式','BUTTONS CONNECTED · PRACTICE');
    $('#demo-badge').textContent=say('体验','PRACTICE');
  }
  document.body.classList.toggle('demo-mode',Boolean(snap.demo));
  $('#sim-open').textContent = say('演示按键','Demo keys');
  document.body.classList.toggle('mouse-testing',Boolean(snap.sim_input));
  $('#physical-header').textContent = snap.sim_input?say('支持鼠标测试','MOUSE TEST ENABLED'):say('实体按键操作','PHYSICAL BUTTONS');
  $('#sim-open').textContent=say('测试按键','TEST BUTTONS');
  $('#motion').setAttribute('aria-label',say('减少动态效果','Reduce motion'));
  $('#footnote').textContent = say('本地教学模拟 · 不创建云资源','LOCAL TEACHING SIMULATION · NO CLOUD RESOURCES');
  $('#physical-header').textContent += say(` · 已用 ${snap.visit_plays}/${snap.visit_limit} 次`, ` · ${snap.visit_plays}/${snap.visit_limit} plays used`);
  $('#footer-status').textContent = snap.demo ? 'SIMULATION ONLINE' : 'LOCAL SYSTEM';
  const kind = ['IDLE','MODE_LOBBY','MISSION_SELECT','SETTINGS','OPERATOR','VISIT_DONE'].includes(snap.state) ? snap.state : 'BUILD';
  document.body.classList.toggle('attract-mode',kind==='IDLE');
  const key = `${kind}/${lang}/${snap.session_id || ''}/${kind==='MODE_LOBBY'?snap.mode:''}/${kind==='MISSION_SELECT'?snap.menu_mission_id:''}/${kind==='SETTINGS'?`${settingsRevision}/${snap.settings_error}`:''}`;
  if (key !== pageKey) {
    attractController?.destroy(); attractController = null;
    if(kind === 'IDLE' && $('#simulator').open) $('#simulator').close();
    // Keep the same physical-input control and its listeners when the page changes.
    // Park it outside the screen before replacing any markup containing it.
    if($('#screen').contains(kiro)) $('#kiro-dock-slot').append(kiro);
    pageKey = key; graphKey = ''; selectedNode = null;
    $('#screen').className = kind === 'BUILD' ? 'build-screen' : 'intro-screen';
    if (kind === 'IDLE') drawAttract();
    else if (kind === 'MODE_LOBBY' || kind === 'MISSION_SELECT') drawLobby();
    else if (kind === 'VISIT_DONE') $('#screen').innerHTML = `<section class="attention-screen"><p class="eyebrow">THANK YOU / NEXT PLAYER</p><h1>${say('3 次体验已结束','Your 3 plays are complete')}</h1><p>${say('谢谢参与！请把机会留给下一位。','Thanks for playing! Please give the next visitor a turn.')}</p><p id="handoff-clock"></p></section>`;
    else if (kind === 'SETTINGS') $('#screen').innerHTML = settingsMarkup(snap, lang, services);
    else if (kind === 'OPERATOR') $('#screen').innerHTML = `<section class="attention-screen"><p class="eyebrow">PLEASE WAIT</p><h1>${say('设备需要检查','Device needs attention')}</h1><p>${say('请先停止拍击，联系现场工作人员。','Please stop pressing the wall and ask event staff for help.')}</p></section>`;
    else drawBuild();
  }
  if ($('#back')) $('#back').onclick = () => post('/api/game/leave');
  if (kind === 'BUILD') updateBuild();
  else energy.attach(null,null,kind,true);
  const kiroSlot=kind==='IDLE'?$('#hero-kiro-slot'):$('#kiro-dock-slot');
  if(kiro.parentElement!==kiroSlot)kiroSlot.append(kiro);
  kiro.classList.toggle('kiro-hero',kind==='IDLE');
  kiro.setAttribute('aria-label',kind==='IDLE'?say('点击Kiro 按键，开始游戏','Press Kiro to start'):say('Kiro 按键','Kiro button'));
  $('#kiro-start-title').textContent=say('开始游戏','Start game');
  kiro.querySelector(':scope > strong').textContent='KIRO';
  updateKiroGuide();
  energy.setMotion({reduced:reduceMotion,paused:visualPaused||snap.paused||['COUNTDOWN','SETTLING','INTERRUPTED'].includes(snap.state)});
}
function drawAttract() {
  $('#screen').innerHTML = `<section class="signal-attract installation-attract"><div class="signal-title"><p class="eyebrow">BRIDGE WITH SIGNAL / ${say('实体按钮互动装置','PHYSICAL BUTTON EXPERIENCE')}</p><div class="start-key-badge"><b><img src="/branding/kiro.svg" alt="Kiro" width="40" height="40"></b><span>${say('紫色 Kiro · 开始键','PURPLE KIRO · START')}</span></div><h1>${say('点击 <b>Kiro</b> 按键<br><em>开始游戏</em>','Press <b>Kiro</b><br><em>to start the game</em>')}</h1><div class="hero-start"><div id="hero-kiro-slot"></div><div class="hero-start-help"><strong>${say('找到这个图案<br>按一下实体键','FIND THIS SYMBOL<br>PRESS THE REAL BUTTON')}</strong><span>${say('16 个服务键 + 1 个 Kiro 开始键','16 SERVICE KEYS + 1 KIRO START KEY')}</span><small>${say('长按 Kiro 2 秒进入设置','HOLD KIRO 2s FOR SETTINGS')}</small></div></div><p class="installation-summary">${say('看屏幕线索，拍方形服务面板。<br>把云服务接成你自己的架构。','Read a clue. Hit a square service panel.<br>Connect the services into your own architecture.')}</p><div class="installation-promise"><span>${say('所有操作，只用实体按键','EVERY ACTION USES PHYSICAL BUTTONS')}</span><span>${say('第一次玩，选「引导构建」','FIRST TIME? TRY GUIDED BUILD')}</span></div></div>${renderAttractDemo(lang)}</section>`;
  attractController=mountAttractDemo(document.querySelector('[data-attract-demo]'),{lang,reducedMotion:reduceMotion});
}
function drawLobby() {
  const rules = mode => `<div class="onboarding-rule"><strong>${say('开始前，记住这三步','Three steps before you start')}</strong>${mode === 'FREE' ? say('① 拍服务键选择能力　② 单击 Kiro 分析组合<br>③ 双击确认完整方案；长按 2 秒返回编辑','① Hit services to select　② Press Kiro to analyze<br>③ Double press to confirm a complete workflow; hold 2s to edit') : say('① 看屏幕上的能力线索　② 找到墙上的对应服务<br>③ 拍一下服务键接通它。每步 10 秒，拍错或超时结束。','① Read the capability clue　② Find its service on the wall<br>③ Hit the service to connect it. 10s per step; wrong or late hits end the run.')}</div>`;
  const options=[['GUIDED','引导构建','Guided build','跟随能力线索，让信号通过完整的架构。','Follow capability clues. Connect the complete workflow.'],['RUSH60_RANKED','60 秒竞速','Builder rush','在 60 秒内接通信号桥。拍错或超时，架构垮塌。','Every step matters. A wrong or missed hit collapses the flow.'],['FREE','自由探索','Free exploration','组合服务，发现它们能构建的方案。','Combine services. Discover the workflows they can create.']];
  if(snap.state==='MISSION_SELECT') {
    const eligible=missions.filter(m=>m.ranked), current=eligible.find(m=>m.id===snap.menu_mission_id)||{title:{zh:'随机方案',en:'Random workflow'},story:{zh:'从全部 13 个教学方案中抽取，本次体验尽量不重复。拍 Bedrock 选择随机，或拍前两排服务键指定场景。',en:'Draw from all 13 examples without repeats in this visit. Hit Bedrock for random, or a first-two-row service key for a specific scenario.'}};
    const index=eligible.indexOf(current);
    $('#screen').innerHTML=`<section class="single-choice physical-menu"><div class="choice-copy"><p class="eyebrow">GUIDED BUILD / ${say('选择场景','CHOOSE A SCENARIO')} ${index<0?'RANDOM':String(index+1).padStart(2,'0')}</p><h1>${esc(t(current.title))}</h1><p>${esc(t(current.story))}</p><div class="physical-confirm">${say('按亮灯方块选场景<br><b>单击Kiro 键开始</b>','HIT A LIT PANEL TO CHOOSE<br><b>PRESS KIRO TO BEGIN</b>')}</div>${rules('GUIDED')}</div>${navigationMarkup(snap,lang,services)}</section>`;
  } else {
    const current=options.find(m=>m[0]===snap.mode)||options[0];
    $('#screen').innerHTML=`<section class="single-choice physical-menu"><div class="choice-copy"><p class="eyebrow">CHOOSE YOUR SIGNAL PATH</p><h1>${say(current[1],current[2])}</h1><p>${say(current[3],current[4])}</p><div class="physical-confirm">${say('按亮灯方块选模式<br><b>单击Kiro 键确认</b>','HIT A LIT PANEL TO CHOOSE<br><b>PRESS KIRO TO CONFIRM</b>')}</div>${rules(current[0])}</div>${navigationMarkup(snap,lang,services)}</section>`;
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
    else if(snap.notice==='FREE_TIME_UP') html=`<div class="rail-status"><h2>${say('探索时间到','Exploration time is up')}</h2></div><p>${say('已结束本局；未确认的组合不计为完成。','This run has ended. Unconfirmed combinations do not count as completed.')}</p>`;
    else if(graph?.status==='complete') html=`<div class="rail-status success-label"><span class="eyebrow">SIGNAL CONNECTED / BRIDGE COMPLETE</span><h2>${say('信号桥已贯通','The signal is through.')}</h2></div><p>${say('所有必要能力已接通','All required capabilities connected')} <span class="completion-count">${graph.connected_count}/${graph.required_count}</span></p>`;
    else if(snap.state==='SETTLING') html=`<div class="rail-status"><span class="eyebrow">VERIFYING INPUTS</span><h2>${say('正在结算…','Settling…')}</h2></div><p>${say('正在确认截止前的最后一次拍击。','Verifying the last hit before the deadline.')}</p>`;
    else if(snap.mode==='FREE') html=`<div class="rail-status"><span class="eyebrow">${snap.free_review?'REVIEW WORKFLOW':'COMPOSE YOUR IDEA'}</span><h2>${snap.free_review?esc(t(graph?.title)):say('拍下服务，组合能力','Hit a service. Add a capability.')}</h2></div><p>${snap.free_review?say('按下方清单补充或移除服务，再分析','Add or remove the listed services, then analyze again'):say('所有服务：按一次 ×1，再按 ×2，第三次取消 · 双击 Kiro 撤销','Every service: press for ×1, again for ×2, then remove · double Kiro to undo')}</p>`;
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
  const focused=snap.candidates?.find(c=>c.mission_id===snap.focused_candidate_id);
  const changes=focused?`${focused.missing.length?say('请补充：','Add: ')+focused.missing.map(shortName).join(' / '):''} ${focused.extra?.length?say('本例未使用，请移除：','Unused in this example; remove: ')+focused.extra.map(shortName).join(' / '):''}`:'';
  target.innerHTML=`<p class="free-note">${say('匹配服务组合，不验证连接方式、权限或生产可用性。','Service-set matching does not validate wiring, permissions or production readiness.')} ${esc(changes)}</p>${snap.notice==='UNSUPPORTED'?`<p class="free-note">${say('示例库未收录这组组合，不能据此判断你的架构对错。可调整服务后再分析。','This combination is not in the examples; that does not make your architecture wrong. Adjust and analyze again.')}</p>`:''}<div class="candidate-list">${(snap.candidates||[]).map(c=>`<div class="candidate ${c.mission_id===snap.focused_candidate_id?'chosen':''}"><strong>${esc(t(c.title))}</strong><span>${c.status==='VALID_COMPLETE'?say('组合匹配','Set match'):say('相近示例','Similar example')}</span></div>`).join('')}</div>`;
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
  if(edge.route) {
    const top=edge.route==='top', sx=s.x+s.w/2, tx=tgt.x+tgt.w/2;
    const sy=top?s.y:s.y+s.h, ty=top?tgt.y:tgt.y+tgt.h;
    const bend=top?Math.min(sy,ty)-65:Math.max(sy,ty)+60;
    return `M${sx},${sy} C${sx},${bend} ${tx},${bend} ${tx},${ty}`;
  }
  if(edge.kind==='observe' || edge.kind==='control' || edge.kind==='side') {
    const above=s.y>tgt.y;
    const sx=s.x+s.w/2,sy=above?s.y:s.y+s.h,tx=tgt.x+tgt.w/2,ty=above?tgt.y+tgt.h:tgt.y;
    // Route long observability branches below the main lane, away from service boxes.
    const bend=above?(sy+ty)/2:Math.max(sy+25,ty-25);
    return `M${sx},${sy} C${sx},${bend} ${tx},${bend} ${tx},${ty}`;
  }
  const reverse=s.x>tgt.x;
  const sx=reverse?s.x:s.x+s.w,sy=s.y+s.h/2,tx=reverse?tgt.x+tgt.w:tgt.x,ty=tgt.y+tgt.h/2;
  if(reverse){const bend=Math.max(18,(sx-tx)/2);return `M${sx},${sy} C${sx-bend},${sy} ${tx+bend},${ty} ${tx},${ty}`;}
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
    $('#graph-wrap').innerHTML=`<svg id="architecture" viewBox="0 ${top} 1280 ${bottom-top}" preserveAspectRatio="xMidYMid meet" role="group" aria-label="${esc(t(graph.title))}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 1L8 5L0 9" fill="none" stroke="context-stroke" stroke-width="1.4"/></marker></defs><rect x="145" y="${top+18}" width="978" height="${bottom-top-36}" rx="24" class="cloud-boundary"/><text x="168" y="${top+43}" class="boundary-label">${say('服务交互 / 教学示意','SERVICE INTERACTIONS / TEACHING EXAMPLE')}</text>${graph.edges.map(edge=>`<g class="flow-edge ${edge.kind}" data-edge="${edge.id}"><path class="edge-base" d="${pathFor(edge,boxes)}" marker-end="url(#arrow)" ${edge.bidirectional?'marker-start="url(#arrow)"':''}/><path class="edge-stream" d="${pathFor(edge,boxes)}"/><text class="edge-label"><textPath href="#label-${edge.id}" startOffset="50%" text-anchor="middle">${esc(t(edge.label))}</textPath></text><path id="label-${edge.id}" d="${pathFor(boxes.get(edge.source).x>boxes.get(edge.target).x?{...edge,source:edge.target,target:edge.source}:edge,boxes)}" fill="none" stroke="none"/></g>`).join('')}<g class="io-node source"><rect x="12" y="245" width="110" height="64" rx="12"/><text x="67" y="269" class="io-label">INPUT</text><text x="67" y="291">${esc(t(graph.io.input))}</text></g><g class="io-node sink"><rect x="1150" y="245" width="115" height="64" rx="12"/><text x="1207" y="269" class="io-label">OUTPUT</text><text x="1207" y="291">${esc(t(graph.io.output))}</text></g>${graph.nodes.map((n,i)=>`<g class="node-position" transform="translate(${n.x} ${n.y})"><foreignObject width="168" height="128" style="overflow:visible"><${debug?'button':'div'} xmlns="http://www.w3.org/1999/xhtml" class="graph-node" data-node="${n.node_id}" style="--fall-delay:${i*90}ms;--tilt:${i%2?6:-5}deg" ${decorative||!debug?'tabindex="-1"':''}>${nodeBody(n)}</${debug?'button':'div'}></foreignObject></g>`).join('')}</svg>`;
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
    $('#graph-caption').textContent=t(graph.architecture_note)||t(graph.scope);
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
  if($('#handoff-clock')) $('#handoff-clock').textContent=say(`${Math.ceil((snap.handoff_remaining_ms||0)/1000)} 秒后迎接下一位`, `Ready for the next visitor in ${Math.ceil((snap.handoff_remaining_ms||0)/1000)}s`);
  const idleRemaining=snap.idle_return_remaining_ms==null?null:Math.max(0,snap.idle_return_remaining_ms-(online?performance.now()-receivedAt:0));
  $('#idle-return').textContent=idleRemaining!=null&&idleRemaining<=15000?say(`${Math.ceil(idleRemaining/1000)} 秒无人操作后回首页`, `Home in ${Math.ceil(idleRemaining/1000)}s if idle`):'';
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
  if(e.key==='`'&&snap?.sim_input){if(!$('#simulator').open)$('#simulator').show();fillSimulator();return;}
  const control=e.target.closest?.('button,a,input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="button"]');
  if((e.code==='Space'||e.code==='Enter')&&!e.repeat&&!kiroKey&&!$('#simulator').open&&(!control||control===kiro)){
    e.preventDefault();kiroKey=e.code;kiroLevel(true);
  }
});
document.addEventListener('keyup',e=>{if(e.code===kiroKey){e.preventDefault();kiroKey=null;kiroLevel(false);}});
window.addEventListener('blur',()=>{kiroKey=null;kiroLevel(false);});
document.addEventListener('visibilitychange',()=>{if(document.hidden){kiroKey=null;kiroLevel(false);}});
setInterval(()=>{const progress=kiroDown?Math.min(1,(performance.now()-kiroDownAt)/2000):0;kiro.style.setProperty('--hold',`${progress*360}deg`);},50);
function renderVoiceControls(state) {
  const enabled=state.enabled;
  $('#voice-toggle').textContent=enabled?say('语音开','Voice on'):say('语音关','Voice off');
  $('#voice-toggle').setAttribute('aria-pressed',String(enabled));
  $('#voice-toggle').setAttribute('aria-label',enabled?say('关闭语音引导','Mute voice guidance'):say('开启语音引导','Enable voice guidance'));
  $('#voice-replay').textContent=state.blocked?say('开启声音','Enable audio'):say('重听','Replay');
  $('#voice-replay').disabled=!currentGuide?.audioId;
  $('#voice-status').textContent=state.blocked?say('语音等待启用，请看文字提示','Follow the text while audio is unavailable'):state.unavailable?say('语音暂不可用，请看文字提示','Audio unavailable. Follow the text.'):state.playing?say('正在讲解…','Speaking…'):'';
  $('.voice-controls').dataset.status=state.status;
}
function updateKiroGuide() {
  currentGuide=guidanceFor(snap,lang,online);
  const html=guidanceMarkup(currentGuide,lang);
  if($('#kiro-guide').innerHTML!==html)$('#kiro-guide').innerHTML=html;
  $('#kiro-guide').dataset.tone=currentGuide.tone;
  $('#kiro-guide').setAttribute('aria-label',say('现在怎么操作','What to do now'));
  const rushProtected=String(snap?.mode).startsWith('RUSH')&&['PREPARE','COUNTDOWN','ACTIVE','SETTLING'].includes(snap?.state);
  $('#home').hidden=!snap||snap.state==='IDLE'||rushProtected;
  $('#home').textContent=say('回首页','Home');
  const inMenus=['IDLE','MODE_LOBBY','MISSION_SELECT','RESULT','INTERRUPTED'].includes(snap?.state);
  $('#physical-console-status').innerHTML=`<strong>${inMenus?say('D4 · 设置','D4 · SETTINGS'):snap?.state==='SETTINGS'?say('Kiro 单击返回','PRESS KIRO TO RETURN'):say('Kiro · 开始键','KIRO · START')}</strong>${snap?.ui_settings?.voice_enabled?say('语音开','VOICE ON'):say('语音关','VOICE OFF')} · ${snap?.ui_settings?.volume??80}%`;
  kiro.disabled=!snap?.sim_input||!online;
  voiceGuide.update(currentGuide,lang);
  renderVoiceControls(voiceGuide.state);
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
