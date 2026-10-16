// A lightweight, local illustration of the physical wall. This never sends game inputs.
// Slots follow config/hardware.json display_grid; the example follows AI Vision.
const wall = [
  ['A1', 'EC2', 'EC2', 'ec2'], ['A2', 'S3', 'S3', 's3'],
  ['B1', 'API_GATEWAY', 'API Gateway', 'api-gateway'], ['B2', 'CLOUDFRONT', 'CloudFront', 'cloudfront'],
  ['A3', 'LAMBDA', 'Lambda', 'lambda'], ['A4', 'DYNAMODB', 'DynamoDB', 'dynamodb'],
  ['B3', 'IOT_CORE', 'IoT Core', 'iot-core'], ['B4', 'SQS', 'SQS', 'sqs'],
  ['C1', 'BEDROCK', 'Bedrock', 'bedrock'], ['C2', 'AGENTCORE', 'AgentCore', 'agentcore'],
  ['D1', 'TRANSCRIBE', 'Transcribe', 'transcribe'], ['D2', 'POLLY', 'Polly', 'polly'],
  ['C3', 'SAGEMAKER_AI', 'SageMaker AI', 'sagemaker'], ['C4', 'REKOGNITION', 'Rekognition', 'rekognition'],
  ['D3', 'CLOUDWATCH', 'CloudWatch', 'cloudwatch'], ['D4', 'COGNITO', 'Cognito', 'cognito'],
];
const example = [
  {key: 'S3', name: 'S3', icon: 's3', zh: '存放图片', en: 'Store image'},
  {key: 'LAMBDA', name: 'Lambda', icon: 'lambda', zh: '触发分析', en: 'Run analysis'},
  {key: 'REKOGNITION', name: 'Rekognition', icon: 'rekognition', zh: '识别图像', en: 'Recognize image'},
  {key: 'DYNAMODB', name: 'DynamoDB', icon: 'dynamodb', zh: '保存结果', en: 'Save result'},
];
const copy = {
  zh: {
    label: '按钮墙玩法演示：点击紫色 Kiro 按键开始，根据屏幕线索拍服务键，把云服务连成完整架构。16 个服务面板和独立 Kiro 键均为正方形。',
    title: '16 个服务键 + 1 个 Kiro 开始键', sample: '玩法演示',
    screen: '架构屏幕', mission: '构建步骤 · 非调用链',
    wall: '云服务按钮墙', start: 'Kiro 键', kiro: '点击 Kiro 开始游戏',
    steps: ['点击Kiro 键', '看线索 · 拍服务', '接通完整架构'],
    intro: '先点击紫色 Kiro 按键，再按提示选择模式和场景。',
    hit: (node) => `线索「${node.zh}」 → 拍 ${node.name} 服务键`,
    complete: '完成！你亲手搭出了 AI 视觉识别架构。',
    still: '点击Kiro 键 → 跟线索拍服务键 → 架构逐步接通',
    ready: '等待开始', progress: (n) => `已接通 ${n} / 4`, done: '架构已接通',
  },
  en: {
    label: 'How the wall works: press the purple Kiro button. Hit square service buttons to match the on-screen clues and connect a cloud architecture.',
    title: '16 service keys + Kiro start key', sample: 'HOW IT WORKS',
    screen: 'ARCHITECTURE SCREEN', mission: 'BUILD STEPS / NOT API CALLS',
    wall: 'CLOUD SERVICE WALL', start: 'KIRO', kiro: 'Press Kiro to start',
    steps: ['Press Kiro', 'Read clue · hit service', 'Connect the workflow'],
    intro: 'Press purple Kiro button, then choose a mode and scenario.',
    hit: (node) => `Clue: ${node.en.toLowerCase()} → hit ${node.name}`,
    complete: 'Connected! You have built an AI vision workflow.',
    still: 'Press Kiro → match clues with service buttons → connect the workflow',
    ready: 'READY TO START', progress: (n) => `${n} / 4 CONNECTED`, done: 'WORKFLOW CONNECTED',
  },
};
const tap = `<span class="ad-tap"><svg viewBox="0 0 44 50" aria-hidden="true"><path d="M14 29V9a4 4 0 0 1 8 0v14-3a4 4 0 0 1 7 0v4-2a4 4 0 0 1 7 0v5-2a4 4 0 0 1 7 0v8c0 9-7 15-16 15h-2c-5 0-8-3-11-7L4 30a4 4 0 0 1 6-5l4 4Z" fill="#ffd900" stroke="#141414" stroke-width="2.8" stroke-linejoin="round"/></svg></span>`;
const mounts = new WeakMap();

/** Return the non-interactive, responsive wall illustration for the attract screen. */
export function renderAttractDemo(lang = 'zh') {
  const language = lang === 'en' ? 'en' : 'zh';
  const c = copy[language];
  return `<section class="attract-demo" data-attract-demo data-lang="${language}" data-step="0" role="figure" aria-label="${c.label}">
    <div class="ad-heading"><strong>${c.title}</strong><span>${c.sample}</span></div>
    <div class="ad-scene" aria-hidden="true">
      <div class="ad-wall-area"><div class="ad-equipment-label"><span>${c.wall}</span><i>4 × 4</i></div>
        <div class="ad-wall">${wall.map(([slot, key, name, file]) => `<div class="ad-service" data-demo-service="${key}"><span class="ad-slot">${slot}</span>${file ? `<img src="/icons/${file}.svg" alt="" width="26" height="26">` : `<span class="ad-text-icon">${key === 'IOT_CORE' ? 'IoT' : 'EC2'}</span>`}<strong>${name}</strong>${tap}</div>`).join('')}</div>
      </div>
      <div class="ad-side">
      <div class="ad-monitor">
        <div class="ad-monitor-top"><span><i></i>${c.screen}</span><b>${c.mission}</b></div>
        <div class="ad-flow">${example.map((node, i) => `<div class="ad-node${i === 0 ? ' is-next' : ''}" data-demo-node="${node.key}">
          <img src="/icons/${node.icon}.svg" alt="" width="32" height="32"><strong>${node.name}</strong><small>${node[language]}</small>
          <span class="ad-node-check">✓</span>${i < example.length - 1 ? '<span class="ad-link">·</span>' : ''}
        </div>`).join('')}</div>
        <div class="ad-monitor-bottom"><span class="ad-monitor-progress">${c.ready}</span><span class="ad-progress-dots">${example.map(() => '<i></i>').join('')}</span></div>
      </div>
        <div class="ad-start-area"><span class="ad-start-label">${c.start}<b>KIRO</b></span><div class="ad-kiro is-target"><img src="/branding/kiro.svg" alt="" width="64" height="64"><strong>KIRO</strong>${tap}</div><strong class="ad-start-instruction">${c.kiro}</strong></div>
      </div>
    </div>
    <div class="ad-caption"><ol class="ad-steps">${c.steps.map((step, i) => `<li${i === 0 ? ' class="is-current"' : ''}><b>0${i + 1}</b><span>${step}</span></li>`).join('')}</ol><p class="ad-current-caption">${c.intro}</p></div>
  </section>`;
}

/** Mount after inserting renderAttractDemo(). Destroy on page changes; update motion in applyMotion(). */
export function mountAttractDemo(root, {lang, reducedMotion = false, paused = false} = {}) {
  const panel = root?.matches?.('[data-attract-demo]') ? root : root?.querySelector?.('[data-attract-demo]');
  if (!panel) return {destroy() {}, setReducedMotion() {}, setPaused() {}};
  mounts.get(panel)?.destroy();
  const c = copy[(lang || panel.dataset.lang) === 'en' ? 'en' : 'zh'];
  let step = 0, timer = null, destroyed = false, motionInitialized = false;
  let reduced = Boolean(reducedMotion), isPaused = Boolean(paused);
  const nodes = Array.from(panel.querySelectorAll('[data-demo-node]'));
  const tiles = Array.from(panel.querySelectorAll('[data-demo-service]'));
  const dots = Array.from(panel.querySelectorAll('.ad-progress-dots i'));
  const steps = Array.from(panel.querySelectorAll('.ad-steps li'));
  const kiro = panel.querySelector('.ad-kiro');
  const caption = panel.querySelector('.ad-current-caption');
  const progress = panel.querySelector('.ad-monitor-progress');
  function display(frame) {
    panel.dataset.step = String(frame);
    panel.dataset.static = String(reduced);
    const count = Math.min(frame, example.length);
    nodes.forEach((node, i) => {
      node.classList.toggle('is-connected', i < count);
      node.classList.toggle('is-next', i === count && frame < 5);
    });
    dots.forEach((dot, i) => dot.classList.toggle('is-connected', i < count));
    tiles.forEach((tile) => {
      const index = example.findIndex(node => node.key === tile.dataset.demoService);
      tile.classList.toggle('is-hit', index >= 0 && index < count);
      tile.classList.toggle('is-target', !reduced && frame > 0 && frame < 5 && index === frame - 1);
    });
    kiro.classList.toggle('is-target', !reduced && frame === 0);
    steps.forEach((item, i) => item.classList.toggle('is-current', reduced || i === (frame === 0 ? 0 : frame === 5 ? 2 : 1)));
    progress.textContent = frame === 0 ? c.ready : frame === 5 ? c.done : c.progress(count);
    caption.textContent = reduced ? c.still : frame === 0 ? c.intro : frame === 5 ? c.complete : c.hit(example[frame - 1]);
  }
  function stop() {
    clearTimeout(timer);
    timer = null;
  }
  function schedule() {
    stop();
    panel.classList.toggle('ad-paused', isPaused || document.hidden);
    if (destroyed || reduced || isPaused || document.hidden) return;
    timer = setTimeout(() => {
      if (!panel.isConnected) { controller.destroy(); return; }
      step = (step + 1) % 6;
      display(step);
      schedule();
    }, step === 0 || step === 5 ? 3200 : 2600);
  }
  function onVisibility() { schedule(); }
  const controller = {
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
      mounts.delete(panel);
    },
    setReducedMotion(value) {
      const next = Boolean(value);
      if (motionInitialized && next === reduced) return;
      reduced = next;
      motionInitialized = true;
      step = reduced ? 5 : 0;
      display(step);
      schedule();
    },
    setPaused(value) {
      isPaused = Boolean(value);
      panel.classList.toggle('ad-paused', isPaused);
      schedule();
    },
  };
  document.addEventListener('visibilitychange', onVisibility);
  mounts.set(panel, controller);
  controller.setReducedMotion(reduced);
  controller.setPaused(isPaused);
  return controller;
}
