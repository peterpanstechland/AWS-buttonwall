/** State-specific instructions. Gestures mirror GameEngine._gesture; never issue game actions here. */
export function guidanceFor(snapshot, lang = 'zh', online = true) {
  const guide = basicGuidanceFor(snapshot, lang, online);
  const s = snapshot || {};
  if (s.state === 'IDLE' && s.ui_settings?.welcome_reminder === false) return {...guide, audioId:null, repeatMs:0};
  if (!online || s.state !== 'RESULT') return guide;
  const missionId = s.mode?.startsWith('RUSH') ? s.last_completed_graph?.id
    : s.final_state === 'VALID' && !s.failure ? s.mission?.id : null;
  if (!missionId) return guide;
  const explanation = `solution_${missionId.toLowerCase()}`;
  return {...guide, audioId: explanation, audioIds: [explanation, guide.audioId].filter(Boolean),
    audioKey: `${s.session_id}/explanation/${missionId}`,
    detail: (lang === 'en' ? 'Listen to the completed workflow explanation. Hit CloudFront to replay. ' : '正在解说已完成的方案，按 CloudFront 可再听一次。') + guide.detail,
    gestures: [...guide.gestures, {gesture: 'CloudFront', label: lang === 'en' ? 'Replay explanation' : '再听方案解说'}]};
}

function basicGuidanceFor(snapshot, lang = 'zh', online = true) {
  const s = snapshot || {};
  const en = lang === 'en';
  const say = (zh, english) => en ? english : zh;
  const translated = value => typeof value === 'string' ? value : value?.[en ? 'en' : 'zh'] || value?.zh || value?.en || '';
  const gesture = (type, zh, english) => ({gesture: type, label: say(zh, english)});
  const session = s.session_id || 'lobby';
  const make = (key, title, detail, gestures, audioId, options = {}) => ({
    key, title, detail, gestures, audioId, audioKey: `${session}/${key}`, priority: 0,
    timed: false, tone: 'normal', repeatMs: 0, idleReturnSeconds: s.idle_return_remaining_ms == null ? null : Math.ceil(s.idle_return_remaining_ms / 1000),
    footnote: say('实体服务键选能力 · Kiro 键负责导航', 'WALL KEYS SELECT CAPABILITIES · KIRO NAVIGATES'), ...options,
  });
  const holdBack = gesture('HOLD', '返回模式选择', 'Back to modes');
  const resultGestures = next => [gesture('CLICK', next ? '下一场景' : '再玩一次', next ? 'Next scenario' : 'Play again'), gesture('DOUBLE', '选择模式', 'Choose mode'), gesture('HOLD', '回首页，也可拍 SageMaker AI', 'Home, or hit SageMaker AI'), gesture('Cognito', '设置', 'Settings')];

  if (!online) return make('offline', say('连接恢复后再继续', 'Waiting for connection'), say('正在自动重连。请先停下拍击，恢复后按屏幕提示操作。', 'Reconnecting automatically. Stop pressing buttons and wait for the screen to recover.'), [gesture('WAIT', '等待自动重连', 'Wait for reconnection')], 'offline', {priority: 3, tone: 'warning'});
  if (!snapshot) return make('loading', say('正在准备游戏', 'Getting ready'), say('连接完成后，按 Kiro 键开始。', 'Press Kiro once the engine is ready.'), [gesture('WAIT', '请稍候', 'Please wait')], null);
  if (s.state === 'VISIT_DONE' || (['RESULT','INTERRUPTED'].includes(s.state) && s.visit_remaining === 0)) return make('visit_done', say('3 次体验已结束，谢谢参与！','Your 3 plays are complete. Thank you!'), (s.state==='VISIT_DONE'?say('请把机会留给下一位，欢迎页将自动恢复。','Please give the next visitor a turn. The welcome page returns automatically.'):say('请把机会留给下一位。按 Kiro 结束体验，随后自动回到欢迎页。','Please give the next visitor a turn. Press Kiro to finish; the welcome screen returns automatically.')), s.state==='VISIT_DONE'?[]:[gesture('CLICK','结束体验','Finish visit')], 'visit_done', {priority:2});
  if (s.state === 'OPERATOR') return make('operator', say('设备需要检查', 'Device needs attention'), say('请联系现场工作人员检查按钮连接或配置。修复后可长按 Kiro 回到首页。', 'Ask event staff to check the wall connection or configuration. Once fixed, hold Kiro to return home.'), [gesture('HOLD', '修复后回首页', 'Return home after repair')], 'operator', {priority: 3, tone: 'warning'});
  if (s.state === 'IDLE') return make('welcome', say('按Kiro 键，开始游戏', 'Press Kiro to start playing'), say('紫色 Kiro 键负责开始。跟着屏幕线索，拍服务按钮，搭出云架构。长按 Kiro 两秒，或拍 Cognito，进入设置。', 'Press the purple Kiro button to begin. Follow the screen clues and hit service buttons to build a cloud architecture. Hold Kiro for two seconds or hit Cognito for settings.'), [gesture('CLICK', 'Kiro 键 · 开始', 'Kiro · Start'), gesture('HOLD', '进入设置', 'Open settings'), gesture('Cognito', '进入设置', 'Open settings')], 'welcome', {audioKey: 'lobby/welcome', repeatMs: 60000});
  if (s.state === 'SETTINGS') return make('settings', say('直接拍对应实体键，调整设置', 'Use the wall buttons to change settings'), say('EC2 中文，S3 English；Lambda / DynamoDB 调整音量；API Gateway 语音开关，CloudFront 重听，IoT Core 减少动效。Kiro 或 SageMaker AI 返回，Cognito 回首页。', 'EC2: Chinese, S3: English. Lambda / DynamoDB: volume. API Gateway: voice, CloudFront: replay, IoT Core: reduced motion. Kiro or SageMaker AI goes back; Cognito returns home.'), [gesture('EC2 / S3', '中文 / English', 'Chinese / English'), gesture('Lambda / DynamoDB', '音量 − / ＋', 'Volume − / +'), gesture('API Gateway / CloudFront', '语音开关 / 重听', 'Voice / Replay'), gesture('CLICK', '返回上一页', 'Back')], 'settings', {audioKey: 'settings'});
  if (s.state === 'MODE_LOBBY') {
    const modes = {
      GUIDED: [say('第一次玩？从引导构建开始', 'First time? Try Guided build.'), say('跟着能力线索选择服务；每步 10 秒，拍错或超时会结束本局。拍亮灯的服务键选模式，再单击 Kiro 确认。', 'Follow the clues. Each step allows 10 seconds; a wrong or late hit ends the run. Pick a mode with a lit service button, then press Kiro to confirm.'), 'mode_guided'],
      RUSH60_RANKED: [say('60 秒内，接通更多架构', 'Connect more workflows in 60 seconds.'), say('独立判断服务；每步最多 10 秒，拍错或超时会结束本局。游戏中不暂停。', 'Identify each service yourself. Each step allows 10 seconds; a wrong or late hit ends the run. The clock cannot be paused.'), 'mode_rush'],
      FREE: [say('自由组合，发现服务能做什么', 'Combine services. Discover what they can do.'), say('每局 2 分钟。先拍实体服务键选能力，再用 Kiro 分析、浏览和确认方案。', 'Two minutes per run. Select capabilities on the physical wall, then use Kiro to analyze, browse and confirm a workflow.'), 'mode_free'],
    };
    const [title, detail, audio] = modes[s.mode] || modes.GUIDED;
    return make(`mode/${s.mode}`, title, detail, [gesture('SERVICE', 'EC2 引导 · S3 竞速 · API Gateway 自由', 'EC2 Guided · S3 Race · API Gateway Free'), gesture('CLICK', '确认当前模式', 'Select this mode'), gesture('SageMaker AI', '回到首页', 'Return home'), gesture('Cognito', '设置', 'Settings')], audio, {repeatMs: 20000});
  }
  if (s.state === 'MISSION_SELECT') return make(`mission/${s.menu_mission_id}`, say('拍亮灯的服务键，选择场景', 'Choose a scenario with a lit service button'), say('默认随机方案；拍 Bedrock 选择随机，前两排 8 个服务键指定场景。先拍服务键选择，再单击Kiro 键开始。SageMaker AI 返回模式，Cognito 进入设置。', 'Random is the default. Hit Bedrock for random; the first two rows select specific scenarios. Pick a scenario, then press Kiro to start. SageMaker AI returns to modes; Cognito opens settings.'), [gesture('SERVICE', '前两排 8 键选择场景', 'First two rows: select scenario'), gesture('CLICK', '开始当前场景', 'Start this scenario'), gesture('SageMaker AI', '返回模式选择', 'Back to modes'), gesture('Cognito', '设置', 'Settings')], s.menu_mission_id ? `mission_${s.menu_mission_id.toLowerCase()}` : 'mission', {audioKey: `lobby/mission/${s.menu_mission_id || ''}`, repeatMs: 30000});
  if (s.state === 'PREPARE' || s.state === 'COUNTDOWN') return make(s.state.toLowerCase(), say('松开所有按钮，准备开始', 'Release the buttons. Get ready.'), say('倒计时结束后，看屏幕线索，拍对应的实体服务键。现在还不用拍。', 'After the countdown, read the clue and hit the matching physical service button. Wait for the start signal.'), [gesture('WAIT', '等待倒计时结束', 'Wait for the countdown'), holdBack], 'ready', {audioKey: `${session}/ready`, timed: true, maxAudioMs: 2200});
  if (s.state === 'SETTLING') return make('settling', say('正在确认本局结果', 'Checking your result'), say('请停下拍击，稍候查看结果与下一步操作。', 'Stop pressing the wall. Your result and next steps will appear shortly.'), [gesture('WAIT', '等待结算', 'Wait for the result')], null);
  if (s.state === 'INTERRUPTED') return make('interrupted', say('本局已结束', 'This run has ended'), say('本局不进入正式排名。单击 Kiro 再玩，双击选择模式，长按回首页。', 'This run is not ranked. Press Kiro to play again, double press for modes, or hold to return home.'), resultGestures(false), 'interrupted', {priority: 2, tone: 'warning'});
  if (s.state === 'RESULT' && s.notice === 'FREE_TIME_UP') return make('free_time_up',say('探索时间到','Exploration time is up'),say('本局已结束。单击 Kiro 再玩，双击选择模式。','This run has ended. Press Kiro to play again, or double press to choose a mode.'),resultGestures(false),'free_time_up');
  if (s.state === 'RESULT') {
    if (s.failure) {
      const reasons = {
        WRONG_SERVICE: say('刚才拍下的服务不能接通当前能力。看清当前线索，再试一次。', 'That service did not match the current capability. Read the clue and try again.'),
        STEP_TIMEOUT: say('这一步超过了 10 秒。下次请在计时结束前拍下对应服务键。', 'That step exceeded 10 seconds. Hit the matching service before the step timer ends.'),
        ROUND_TIMEOUT: say('整局时间已到。还有能力没有接通，可以再挑战一次。', 'The session timer ended before the workflow was complete. Try another run.'),
      };
      return make(`failed/${s.failure.reason}`, say('信号中断，再试一次', 'Signal lost. Try again.'), reasons[s.failure.reason] || say('本局已结束，可重试或切换模式。', 'The run has ended. Retry or choose another mode.'), resultGestures(false), 'failed', {priority: 2, tone: 'warning'});
    }
    const next = s.mode === 'GUIDED' && s.final_state === 'VALID';
    return make('complete', say('你把信号桥接通了！', 'You connected the signal bridge!'), next ? say('所有必要能力已接通。单击 Kiro 继续下一个随机场景，或双击换模式。', 'All required capabilities are connected. Press Kiro for the next random scenario or double press to change mode.') : say('已完成本局。单击 Kiro 再玩一次，或双击探索其他模式。', 'Run complete. Press Kiro to play again or double press to explore another mode.'), resultGestures(next), next ? 'guided_complete' : 'complete', {priority: 1, tone: 'success'});
  }
  if (s.state === 'ACTIVE' && s.forfeit_pending) return make('forfeit', say('确定结束本局？', 'End this run?'), say('竞速计时仍在继续。单击 Kiro 取消，双击确认结束。', 'The race clock is still running. Press Kiro to cancel or double press to end this run.'), [gesture('CLICK', '取消，继续游戏', 'Cancel and keep playing'), gesture('DOUBLE', '确认结束本局', 'End this run')], 'forfeit', {priority: 2, timed: true, maxAudioMs: 3000, tone: 'warning'});
  if (s.state === 'ACTIVE' && s.mode === 'FREE') {
    const focused = s.candidates?.find(row => row.mission_id === s.focused_candidate_id) || s.candidates?.[0];
    if (s.free_review && focused) {
      const complete = focused.status === 'VALID_COMPLETE';
      return make(`free_review/${focused.mission_id}/${focused.status}`, complete ? say('这套方案已凑齐，可以确认', 'This workflow is ready to confirm') : say('组合需要调整', 'This combination needs changes'), complete ? say('单击 Kiro 看其他方案，双击确认当前方案。长按返回编辑；拍服务键也会继续编辑。', 'Press Kiro to browse workflows, double press to confirm this one, or hold to edit. A service-button hit also returns to editing.') : say('请按屏幕列出的服务名称补充或移除服务。单击 Kiro 看其他方案，长按返回编辑，再拍服务键补充能力。', 'Add or remove the services listed on screen. Press Kiro to browse, or hold to return to editing and add services on the wall.'), [gesture('CLICK', '查看下个方案', 'Next workflow'), ...(complete ? [gesture('DOUBLE', '确认当前方案', 'Confirm this workflow')] : []), gesture('HOLD', '返回编辑', 'Back to editing')], complete ? 'free_review' : 'free_incomplete');
    }
    const unsupported = s.notice === 'UNSUPPORTED';
    return make(unsupported ? 'free_no_match' : 'free_edit', unsupported ? say('示例库未收录，不能判定对错', 'Not in the examples; not a verdict.') : say('先拍服务键，再分析你的组合', 'Select services, then analyze your combination'), unsupported ? say('服务组合无法说明你的完整设计；未收录不代表架构错误。继续拍实体服务键调整组合，再单击 Kiro 分析。', 'The local examples do not match this combination yet. Adjust the services on the wall, then press Kiro to analyze again.') : say('每个服务按一次选一个，再按选两个，第三次取消。单击 Kiro 分析组合，双击撤销上一步。', 'Every service cycles through one, two, then zero with repeated presses. Press Kiro to analyze; double press to undo the last change.'), [gesture('SERVICE', '选择 / 调整服务', 'Select / adjust services'), gesture('CLICK', '分析组合', 'Analyze'), gesture('DOUBLE', '撤销上一步', 'Undo last change'), holdBack], unsupported ? 'free_no_match' : 'free_edit');
  }
  if (s.state === 'ACTIVE' && s.mode === 'GUIDED' && s.paused) return make('paused', say('已暂停，可以慢慢看线索', 'Paused. Take a moment to read the clue.'), say('计时已暂停。单击 Kiro 继续，再拍对应的实体服务键。', 'The step timer is paused. Press Kiro to resume, then hit the matching physical service button.'), [gesture('CLICK', '继续游戏', 'Resume'), holdBack], 'paused');
  if (s.state === 'ACTIVE') {
    const hint = translated(s.role_hint);
    const guided = s.mode === 'GUIDED';
    const targetNode = guided ? s.graph?.nodes?.find(node => node.required && node.state === 'ready') : null;
    const target = guided ? s.buttons?.find(button => targetNode ? button.key === targetNode.service : s.panels?.[button.id] === 'TARGET_HINT') : null;
    if (target) {
      const names = {EC2:'EC2',S3:'S3',LAMBDA:'Lambda',DYNAMODB:'DynamoDB',API_GATEWAY:'API Gateway',CLOUDFRONT:'CloudFront',IOT_CORE:'IoT Core',SQS:'SQS',BEDROCK:'Bedrock',AGENTCORE:'Bedrock AgentCore',SAGEMAKER_AI:'SageMaker AI',REKOGNITION:'Rekognition',TRANSCRIBE:'Transcribe',POLLY:'Polly',CLOUDWATCH:'CloudWatch',COGNITO:'Cognito'};
      const name = names[target.key] || target.key;
      return make(`active/${s.round_id || ''}/${s.step_epoch || ''}`, say(`请按 ${name} 键`, `Press ${name}`), hint ? say(`当前能力：${hint}。找到标有 ${name} 的服务面板并拍下。`, `Current capability: ${hint}. Find and press the ${name} panel.`) : say(`找到 ${name} 服务面板并拍下。`, `Find and press the ${name} panel.`), [gesture('SERVICE', `${target.slot} · ${name}`, `${target.slot} · ${name}`), gesture('CLICK', '暂停 / 继续', 'Pause / resume'), holdBack], `service_${target.key.toLowerCase()}`, {audioKey: `${session}/guided/${s.round_id || ''}/${s.step_epoch || ''}/${target.key}`, timed: true, maxAudioMs: 5000});
    }
    return make(`active/${s.round_id || ''}/${s.step_epoch || ''}`, hint ? say(`当前能力：${hint}`, `Current capability: ${hint}`) : say('看能力线索，拍对应服务键', 'Read the clue. Hit the matching service.'), say('每步 10 秒；拍错或超时会结束本局。实体服务键负责选择能力。', 'You have 10 seconds per step. A wrong or late hit ends the run. Use physical service buttons to choose the capability.'), [gesture('SERVICE', '拍对应服务键', 'Hit the matching service'), ...(guided ? [gesture('CLICK', '暂停 / 继续', 'Pause / resume'), holdBack] : [gesture('HOLD', '打开结束确认', 'Ask to end this run')])], 'go', {audioKey: `${session}/active/${s.round_id || ''}`, timed: true, maxAudioMs: 2400});
  }
  return make('waiting', say('请按屏幕提示操作', 'Follow the screen instructions'), say('状态正在更新，请稍候。', 'The game is updating. Please wait.'), [gesture('WAIT', '请稍候', 'Please wait')], null);
}

const escaped = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

/** Optional markup helper; insert in a persistent .interaction-guide region. */
export function guidanceMarkup(guide, lang = 'zh') {
  const labels = lang === 'en' ? {CLICK:'KIRO · PRESS',DOUBLE:'KIRO · DOUBLE',HOLD:'KIRO · HOLD 2s',SERVICE:'WALL SERVICE KEY',WAIT:'PLEASE WAIT'} : {CLICK:'Kiro 单击',DOUBLE:'Kiro 双击',HOLD:'Kiro 长按 2 秒',SERVICE:'实体服务键',WAIT:'请稍候'};
  return `<div class="guide-copy"><span class="guide-eyebrow">${lang === 'en' ? 'YOUR NEXT MOVE' : '下一步这样做'}</span><h2>${escaped(guide.title)}</h2><p>${escaped(guide.detail)}</p></div><div class="guide-gestures">${guide.gestures.map(item => `<div class="guide-gesture" data-gesture="${escaped(item.gesture)}"><b>${escaped(labels[item.gesture] || item.gesture)}</b><span>${escaped(item.label)}</span></div>`).join('')}</div>`;
}

/** Local MP3 player: one current prompt, no queue and no network speech dependency. */
export class VoiceGuide {
  constructor(options = {}) {
    this.onChange = options.onChange || (() => {});
    this.lang = 'zh';
    this.guide = null;
    this.lastKey = null;
    this.now = options.now || (() => Date.now());
    this.lastPlayedAt = -Infinity;
    this.token = 0;
    this.destroyed = false;
    this.limitTimer = null;
    this.manifest = null;
    this.manifestFailed = false;
    try { this.storage = options.storage === undefined ? globalThis.localStorage : options.storage; } catch { this.storage = null; }
    let saved;
    try { saved = this.storage?.getItem('wall-voice-enabled'); } catch { /* Storage is optional on locked-down kiosks. */ }
    this.enabled = options.enabled === undefined ? saved !== 'false' : Boolean(options.enabled);
    this.volume = Number.isFinite(Number(options.volume)) ? Math.min(100, Math.max(0, Number(options.volume))) : 100;
    this.state = {enabled: this.enabled, volume: this.volume, status: this.enabled ? 'loading' : 'off', playing: false, blocked: false, unavailable: false, language: this.lang, audioId: null};
    try {
      this.audio = options.audioFactory ? options.audioFactory() : new Audio();
      this.audio.preload = 'auto';
      this.audio.volume = this.volume / 100;
    } catch { this.audio = null; }
    if (options.manifest) {
      this.manifest = options.manifest;
      this.ready = Promise.resolve(this.manifest);
      this.state.status = this.enabled ? 'ready' : 'off';
    } else {
      const fetcher = options.fetcher || globalThis.fetch?.bind(globalThis);
      this.ready = Promise.resolve().then(async () => {
        if (!fetcher) throw new Error('Local audio manifest unavailable');
        const response = await fetcher(options.manifestUrl || '/audio/prompts.json');
        if (!response.ok) throw new Error('Local audio manifest unavailable');
        this.manifest = await response.json();
        if (!this.destroyed) this._emit({status: this.enabled ? 'ready' : 'off'});
        return this.manifest;
      }).catch(() => {
        this.manifestFailed = true;
        if (!this.destroyed) this._emit({status: this.enabled ? 'unavailable' : 'off', unavailable: true});
        return null;
      });
    }
  }

  _emit(change = {}) {
    this.state = {...this.state, ...change, enabled: this.enabled, volume: this.volume, language: this.lang};
    try { this.onChange({...this.state}); } catch { /* UI failures must not affect game inputs. */ }
  }

  stop() {
    this.token += 1;
    clearTimeout(this.limitTimer);
    this.limitTimer = null;
    if (this.audio) {
      this.audio.onended = null;
      this.audio.onerror = null;
      try { this.audio.pause(); this.audio.currentTime = 0; } catch { /* No playable media yet. */ }
    }
    this._emit({playing: false, status: this.enabled ? 'ready' : 'off'});
  }

  update(guide, lang = 'zh') {
    if (this.destroyed) return;
    const language = lang === 'en' ? 'en' : 'zh';
    const key = `${language}/${guide?.audioKey || guide?.key || 'none'}/${guide?.audioId || 'silent'}`;
    this.guide = guide;
    const changed = language !== this.lang || key !== this.lastKey;
    this.lang = language;
    if (!changed) {
      if (this.enabled && guide?.repeatMs && !this.state.playing && !this.state.blocked && !this.state.unavailable && this.now() - this.lastPlayedAt >= guide.repeatMs) void this._play();
      return;
    }
    this.lastKey = key;
    this.stop();
    if (this.enabled && guide?.audioId) void this._play();
  }

  setEnabled(value) {
    if (this.destroyed) return;
    const enabled = Boolean(value);
    if (enabled === this.enabled) return this.enabled;
    this.enabled = enabled;
    try { this.storage?.setItem('wall-voice-enabled', String(this.enabled)); } catch { /* In-memory preference is enough. */ }
    this.stop();
    if (this.enabled && this.guide?.audioId) void this._play();
    return this.enabled;
  }

  setVolume(value) {
    const volume = Number(value);
    if (this.destroyed || !Number.isFinite(volume)) return this.volume;
    const bounded = Math.min(100, Math.max(0, volume));
    if (bounded === this.volume) return this.volume;
    this.volume = bounded;
    if (this.audio) this.audio.volume = this.volume / 100;
    this._emit();
    return this.volume;
  }

  toggle() { this.setEnabled(!this.enabled); return this.enabled; }
  replay() {
    if (this.destroyed) return Promise.resolve(false);
    if (!this.enabled) {
      this.enabled = true;
      try { this.storage?.setItem('wall-voice-enabled', 'true'); } catch { /* Optional persistence. */ }
    }
    return this._play();
  }
  unlock() { return this.state.blocked && this.enabled ? this._play() : Promise.resolve(false); }

  async _play(index = 0) {
    this.stop();
    const token = this.token;
    const guide = this.guide;
    const language = this.lang;
    if (!guide?.audioId || !this.enabled || this.destroyed) return false;
    if (globalThis.document?.hidden) return false;
    this.lastPlayedAt = this.now();
    if (!this.manifest) await this.ready;
    if (token !== this.token || this.destroyed || !this.enabled) return false;
    const playlist = guide.audioIds || [guide.audioId];
    const audioId = playlist[index];
    const prompt = this.manifest?.prompts?.find(item => item.id === audioId);
    const file = prompt?.[language]?.file;
    if (!file || !this.audio) {
      this._emit({status: 'unavailable', unavailable: true, playing: false, audioId: guide.audioId});
      return false;
    }
    this._emit({status: 'loading', playing: false, unavailable: false, audioId: guide.audioId});
    const onError = () => {
      if (token !== this.token) return;
      clearTimeout(this.limitTimer);
      this._emit({status: 'unavailable', playing: false, unavailable: true});
    };
    this.audio.onended = () => {
      if (token !== this.token) return;
      clearTimeout(this.limitTimer);
      this._emit({status: 'ready', playing: false});
      if (index + 1 < playlist.length) void this._play(index + 1);
    };
    this.audio.onerror = onError;
    try {
      this.audio.src = file;
      this.audio.currentTime = 0;
      await this.audio.play();
      if (token !== this.token || this.destroyed) return false;
      this._emit({status: 'playing', playing: true, blocked: false, unavailable: false});
      if (guide.maxAudioMs) this.limitTimer = setTimeout(() => { if (token === this.token) this.stop(); }, guide.maxAudioMs);
      return true;
    } catch (error) {
      if (token !== this.token || this.destroyed) return false;
      if (error?.name === 'NotAllowedError') this._emit({status: 'blocked', playing: false, blocked: true, unavailable: false});
      else if (error?.name !== 'AbortError') onError();
      return false;
    }
  }

  destroy() { this.stop(); this.destroyed = true; this.guide = null; this.onChange = () => {}; }
}
