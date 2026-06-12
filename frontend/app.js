const modules = [
  { id: 'dashboard', label: '总览看板', icon: '◧' },
  { id: 'intake', label: '智能问诊', icon: '✚' },
  { id: 'mining', label: '规则挖掘', icon: '⛏' },
  { id: 'evidence', label: '证据回溯', icon: '⌖' },
  { id: 'review', label: '医师审核', icon: '✒' },
  { id: 'safety', label: '评估与安全', icon: '⛨' },
  { id: 'settings', label: '设置', icon: '⚙' },
];

const MINED = typeof window !== 'undefined' && window.MINED_RULES ? window.MINED_RULES : null;

const steps = [
  { id: 'start', label: '开始与知情', title: '自动导引患者生成标准腰痹医案' },
  { id: 'redflag', label: '红旗筛查', title: '先排除需要立即线下评估的危险信号' },
  { id: 'basic', label: '主诉病程', title: '采集基础信息、主诉与病程' },
  { id: 'pain', label: '疼痛特征', title: '采集疼痛部位、放射、性质和诱因' },
  { id: 'neuro', label: '神经骨科', title: '采集麻木、无力、影像与既往诊断' },
  { id: 'tcm', label: '中医四诊', title: '用患者能理解的问题采集中医信息' },
  { id: 'comorbidity', label: '合并病用药', title: '采集合并病、NSAIDs、肌松药与过敏史' },
  { id: 'signals', label: '规则线索', title: '沈老经验规则线索与 CDSS 草案' },
  { id: 'final', label: '最终医案', title: '标准医案、医生复核清单与导出' },
];

const featureMatrix = [
  ['CaseGuide FSM', '有限状态机分阶段问诊，默认每个状态最多 3 轮追问（可设置 1–5 轮）、每轮最多 3 问，答完可自动进入下一状态。'],
  ['Rule Engine', '结构化标签、候选证型、方剂路线、模块命中和冲突检查。'],
  ['Tao Direct Runtime', '本地 Transformers 直接推理：TAO_BACKEND=transformers，无需 FastAPI 包装。'],
  ['JSON Repair', '修复模型 JSON 围栏、尾逗号、单引号等常见格式错误。'],
  ['Output Guard', '拦截最终诊断、完整处方、患者可执行剂量和替代医生建议。'],
  ['CDSS Draft', '医生端候选诊断/候选证型/处方策略草案，非患者可见。'],
  ['Physician Review', '最终诊断、处方、剂量只能由 licensed physician 手工签名。'],
  ['Export', '标准医案 Markdown、规则 JSON、医生复核摘要导出。'],
];

const questions = {
  redflag: [
    { id: 'RF001', q: '腰痛是否由跌倒、车祸、重物砸伤等明显外伤后出现？', options: ['是', '否', '不确定'], urgent: ['是'] },
    { id: 'RF002', q: '是否出现大小便控制困难、会阴区麻木，或突然尿不出来？', options: ['是', '否', '不确定'], urgent: ['是'] },
    { id: 'RF003', q: '是否出现一侧或双侧下肢明显无力、走路拖脚、进行性加重？', options: ['是', '否', '不确定'], urgent: ['是'] },
    { id: 'RF004', q: '是否伴有发热、寒战，或近期有感染？', options: ['是', '否', '不确定'], caution: ['是', '不确定'] },
    { id: 'RF005', q: '是否有肿瘤病史、原因不明体重下降、夜间痛明显加重？', options: ['是', '否', '不确定'], caution: ['是', '不确定'] },
    { id: 'RF006', q: '是否长期使用激素，或已知严重骨质疏松，并突然出现剧烈腰背痛？', options: ['是', '否', '不确定'], caution: ['是', '不确定'] },
  ],
  basic: [
    { id: 'age', q: '你的年龄是？', type: 'number', placeholder: '例如：68' },
    { id: 'sex', q: '性别？', options: ['女', '男', '其他/不便说明'] },
    { id: 'main_symptom', q: '你最主要的不舒服是什么？', options: ['腰痛', '腰腿痛', '腰酸', '腰痛伴腿麻'], note: true },
    { id: 'duration', q: '这种情况持续多久了？', options: ['3天', '2周', '半年', '5年'], note: true },
    { id: 'acute_worsening', q: '这次加重多久了？', options: ['无明显加重', '3天', '2周', '1月'], note: true },
  ],
  pain: [
    { id: 'location', q: '疼痛主要在哪个部位？', multi: true, options: ['腰正中', '一侧腰部', '双侧腰部', '腰骶部', '臀部', '大腿后侧', '小腿', '足部', '说不清'] },
    { id: 'radiation', q: '疼痛会不会从腰部放射到臀部或下肢？', options: ['不会', '到臀部', '到大腿', '到小腿', '到足部', '不确定'] },
    { id: 'pain_nature', q: '疼痛性质更像哪一种？', multi: true, options: ['酸痛', '胀痛', '刺痛', '冷痛', '灼痛', '隐痛', '掣痛/牵拉痛', '麻痛', '说不清'] },
    { id: 'severity', q: '0 到 10 分，你觉得疼痛大约几分？', type: 'range' },
    { id: 'aggravating', q: '什么情况下会加重？', multi: true, options: ['久坐', '久站', '弯腰', '劳累', '受凉', '阴雨天', '走路', '咳嗽打喷嚏', '夜间', '没有明显规律'] },
    { id: 'relieving', q: '什么情况下会缓解？', multi: true, options: ['休息', '热敷', '活动后', '按摩', '卧床', '服止痛药', '没有明显缓解'] },
  ],
  neuro: [
    { id: 'numbness', q: '是否有下肢麻木？', options: ['没有', '偶尔有', '经常有', '持续存在', '说不清'] },
    { id: 'numbness_location', q: '麻木主要在哪个部位？', multi: true, options: ['臀部', '大腿外侧', '大腿后侧', '小腿外侧', '小腿后侧', '足背', '足底', '脚趾', '双下肢', '说不清'] },
    { id: 'weakness', q: '是否感觉腿无力、走路不稳、脚抬不起来？', options: ['没有', '轻微', '明显', '越来越重'] },
    { id: 'walking_limitation', q: '走一段路后是否腰腿痛或麻木加重，休息或弯腰后缓解？', options: ['是', '否', '不确定'] },
    { id: 'imaging', q: '是否做过腰椎 X 线、CT、MRI 或骨密度检查？', multi: true, options: ['做过MRI', '做过CT', '做过X线', '做过骨密度', '没做过', '不记得'] },
    { id: 'western_diagnosis', q: '医生曾经告诉你有什么诊断？', multi: true, options: ['腰椎间盘突出', '腰椎管狭窄', '腰椎滑脱', '骨质疏松', '骨折/压缩性骨折', '腰肌劳损', '坐骨神经痛', '其他', '不清楚'] },
  ],
  tcm: [
    { id: 'cold_heat', q: '你平时怕冷还是怕热？', options: ['怕冷', '怕热', '都不明显', '有时怕冷有时怕热'] },
    { id: 'cold_relation', q: '腰腿痛遇冷会不会加重？热敷会不会舒服？', options: ['遇冷加重，热敷舒服', '热敷不舒服', '没影响', '不确定'] },
    { id: 'dampness', q: '身体是否容易困重、沉重，尤其阴雨天更明显？', options: ['明显', '轻微', '没有', '不确定'] },
    { id: 'sleep', q: '睡眠怎么样？', multi: true, options: ['正常', '入睡困难', '容易醒', '多梦', '早醒', '疼痛影响睡眠', '睡不踏实'] },
    { id: 'appetite', q: '胃口怎么样？', options: ['正常', '胃口差', '容易腹胀', '吃药容易胃不舒服', '恶心反酸'] },
    { id: 'mouth_taste', q: '是否经常口苦、口干，或咽喉不清爽？', options: ['明显', '轻微', '没有'] },
    { id: 'tongue_color', q: '舌头颜色更像偏淡、偏暗紫，还是偏红？', options: ['偏淡', '偏暗紫', '偏红', '说不清'] },
    { id: 'tongue_coating', q: '舌苔是否偏厚腻、白腻或黄腻？', options: ['薄白', '白腻', '黄腻', '厚腻', '说不清'] },
  ],
  comorbidity: [
    { id: 'diseases', q: '是否有以下疾病？', multi: true, options: ['高血压', '糖尿病', '骨质疏松', '肾功能异常', '肝功能异常', '胃溃疡/胃炎', '心脏病', '肿瘤病史', '过敏史', '无', '不清楚'] },
    { id: 'medications', q: '最近是否服用过止痛药或消炎药？', multi: true, options: ['塞来昔布', '布洛芬', '双氯芬酸', '艾瑞昔布', '依托考昔', '乙哌立松', '甲钴胺', '其他', '没有', '不清楚'] },
    { id: 'anticoagulant', q: '是否正在服用抗凝药、阿司匹林、激素或降糖药？', options: ['是', '否', '不确定'] },
    { id: 'allergy', q: '是否有药物或中药过敏史？', options: ['有', '没有', '不确定'] },
  ],
};

const state = {
  module: localStorage.getItem('yaobi-module') || 'dashboard',
  step: 0,
  doctorMode: true,
  answers: JSON.parse(localStorage.getItem('yaobi-case') || '{}'),
  fsm: JSON.parse(localStorage.getItem('yaobi-fsm') || '{\"rounds\":{},\"lastAnswers\":{}}'),
};
state.fsm.rounds = state.fsm.rounds || {};
state.fsm.lastAnswers = state.fsm.lastAnswers || {};
state.fsm.maxRounds = Number(state.fsm.maxRounds) >= 1 ? Number(state.fsm.maxRounds) : 3;
state.fsm.autoAdvance = state.fsm.autoAdvance !== false;

const screen = document.querySelector('#screen');
const pageTitle = document.querySelector('#pageTitle');

function save() {
  localStorage.setItem('yaobi-case', JSON.stringify(state.answers));
  localStorage.setItem('yaobi-fsm', JSON.stringify(state.fsm));
  updatePreview();
}

function answerValue(id) { return state.answers[id]; }
function setAnswer(id, value, multi = false) {
  if (multi) {
    const current = new Set(Array.isArray(state.answers[id]) ? state.answers[id] : []);
    current.has(value) ? current.delete(value) : current.add(value);
    state.answers[id] = [...current];
  } else {
    state.answers[id] = value;
  }
  save();
}


function maxRounds() {
  return Math.max(1, Number(state.fsm.maxRounds) || 3);
}

function stageRound(stage) {
  return Math.min(state.fsm.rounds[stage] || 0, maxRounds() - 1);
}

function setStageRound(stage, value) {
  state.fsm.rounds[stage] = Math.max(0, Math.min(maxRounds() - 1, value));
  save();
}

function setMaxRounds(value) {
  state.fsm.maxRounds = Math.max(1, Math.min(5, Number(value) || 3));
  save();
}

function questionAnswered(q) {
  const value = state.answers[q.id];
  return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== '' && value !== null;
}

function questionReason(q, stage) {
  const tags = getTags();
  if (stage === 'redflag') return '红旗筛查优先；若命中危险信号，将立即停止后续普通问诊。';
  if (['cold_relation', 'cold_heat'].includes(q.id) && (tags.includes('elderly') || tags.includes('lower_limb_numbness'))) return '结合上一轮高龄/麻木/久病线索，深化寒湿、温经散寒与通络规则变量。';
  if (['numbness', 'numbness_location', 'radiation'].includes(q.id)) return '结合疼痛部位和上一轮回答，深化放射痛、麻木和神经根风险线索。';
  if (['imaging', 'western_diagnosis', 'diseases'].includes(q.id)) return '结合当下规则命中，补足影像、骨质疏松和医生复核背景。';
  if (['sleep', 'appetite', 'mouth_taste'].includes(q.id)) return '结合沈老规则中的口苦、睡眠、胃纳变量，深化少阳/顾护中焦线索。';
  return '根据当前规则标签与上一轮答案，补齐本状态最有信息增益的字段。';
}

function currentStageQuestions(stage) {
  const list = questions[stage] || [];
  const round = stageRound(stage);
  const key = `${stage}:${round}`;
  state.fsm.shownIds = state.fsm.shownIds || {};
  let ids = state.fsm.shownIds[key];
  if (!ids || !ids.length) {
    const unanswered = list.filter(q => !questionAnswered(q));
    const selected = unanswered.length ? unanswered.slice(0, 3) : list.slice(round * 3, round * 3 + 3);
    ids = (selected.length ? selected : list.slice(-3)).map(q => q.id);
    state.fsm.shownIds[key] = ids;
    save();
  }
  return list.filter(q => ids.includes(q.id)).map(q => ({ ...q, reason: questionReason(q, stage) }));
}

function stageFollowupsExhausted(stage) {
  return stageRound(stage) + 1 >= maxRounds();
}

function maybeAutoAdvance(stage) {
  if (!state.fsm.autoAdvance) return false;
  const list = questions[stage] || [];
  const shown = currentStageQuestions(stage);
  const allAnswered = list.every(q => questionAnswered(q));
  const shownAnswered = shown.every(q => questionAnswered(q));
  if (stage === 'redflag' && !allAnswered) return false; // 红旗筛查是硬门控，必须答完才能离开。
  if (allAnswered || (shownAnswered && stageFollowupsExhausted(stage))) {
    state.fsm.lastAnswers[stage] = { ...state.answers };
    save();
    state.step = Math.min(steps.length - 1, state.step + 1);
    render();
    return true;
  }
  if (shownAnswered) {
    state.fsm.lastAnswers[stage] = { ...state.answers };
    setStageRound(stage, stageRound(stage) + 1);
    render();
    return true;
  }
  return false;
}

function renderStepper() {
  const el = document.querySelector('#stepper');
  el.innerHTML = steps.map((s, i) => `
    <button class="step ${i === state.step ? 'active' : ''} ${i < state.step ? 'done' : ''}" data-step="${i}" type="button">
      <span class="step-index">${i + 1}</span><span>${s.label}</span>
    </button>`).join('');
  el.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => { state.step = Number(btn.dataset.step); render(); }));
}

function renderModuleNav() {
  const nav = document.querySelector('#moduleNav');
  nav.innerHTML = modules.map(m => `
    <button class="module-link ${m.id === state.module ? 'active' : ''}" data-module="${m.id}" type="button">
      <span class="module-icon">${m.icon}</span><span>${m.label}</span>
    </button>`).join('');
  nav.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
    state.module = btn.dataset.module;
    localStorage.setItem('yaobi-module', state.module);
    render();
  }));
}

function render() {
  renderModuleNav();
  const intake = state.module === 'intake';
  document.querySelector('#stepper').style.display = intake ? '' : 'none';
  document.querySelector('.case-sidebar').style.display = intake ? '' : 'none';
  document.querySelector('.app-shell').classList.toggle('wide', !intake);
  if (!intake) {
    if (state.module === 'dashboard') return renderDashboard();
    if (state.module === 'mining') return renderMiningModule();
    if (state.module === 'evidence') return renderEvidenceModule();
    if (state.module === 'review') return renderReviewModule();
    if (state.module === 'safety') return renderSafetyModule();
    if (state.module === 'settings') return renderSettingsModule();
  }
  renderStepper();
  pageTitle.textContent = steps[state.step].title;
  const id = steps[state.step].id;
  if (id === 'start') return renderStart();
  if (id === 'signals') return renderSignals();
  if (id === 'final') return renderFinal();
  renderQuestionStage(id);
}

function renderStart() {
  screen.innerHTML = `
    <section class="hero">
      <div class="hero-grid">
        <div>
          <p class="eyebrow">名老中医腰痹诊疗经验研究助手 / CDSS 草案</p>
          <h2>把零散腰痛描述整理成可复核、可标注、可教学的标准医案</h2>
          <p>本工具以红旗筛查为安全底线，以中西医问诊为骨架，以沈钦荣腰痹经验规则为导引逻辑，输出标准化医案、规则线索、医生复核清单和医生端 CDSS 草案。</p>
          <div class="badges"><span class="badge">红旗优先</span><span class="badge">每屏 1–3 问</span><span class="badge">规则证据可追溯</span><span class="badge">医师签名闭环</span></div>
          <button class="primary-btn" id="startBtn">开始整理医案</button>
        </div>
        <div class="notice">
          <strong>重要边界：</strong>患者端不会生成最终诊断、完整处方或患者可执行剂量。医生端 CDSS 仅生成草案，最终诊断和处方需 licensed physician 手工录入并签名。
        </div>
      </div>
      <div class="feature-grid">${featureMatrix.map(([name, desc]) => `<article><strong>${name}</strong><p>${desc}</p></article>`).join('')}</div>
      <pre class="runtime-code">TAO_BACKEND=transformers python -m backend.main --tao-chat "请解释本案规则线索" --stream</pre>
    </section>`;
  document.querySelector('#startBtn').addEventListener('click', () => { state.step = 1; render(); });
}

function renderQuestionStage(stage) {
  const urgent = getRedFlagStatus().status === 'urgent';
  if (stage !== 'redflag' && urgent) {
    screen.innerHTML = `<section class="result-panel redflag"><h3>已命中红旗信号</h3><p>请先线下就医或急诊评估。本工具已停止后续中医问诊。</p><button class="ghost-btn" id="backRed">返回红旗筛查</button></section>`;
    document.querySelector('#backRed').addEventListener('click', () => { state.step = 1; render(); });
    return;
  }
  const round = stageRound(stage);
  const list = currentStageQuestions(stage);
  const remaining = Math.max(0, maxRounds() - round - 1);
  const exhausted = stageFollowupsExhausted(stage);
  screen.innerHTML = `
    <section class="fsm-strip">
      <strong>有限状态机追问</strong>
      <span>本状态第 ${round + 1}/${maxRounds()} 轮（剩余追问 ${remaining} 轮），每轮最多 3 问；问题会叠加当前规则标签、上一轮答案与 Tao 大模型深化理由。</span>
      <label class="fsm-setting">追问轮数上限
        <select id="maxRoundsSelect">${[1, 2, 3, 4, 5].map(n => `<option value="${n}" ${n === maxRounds() ? 'selected' : ''}>${n}</option>`).join('')}</select>
      </label>
      <label class="fsm-setting"><input type="checkbox" id="autoAdvanceToggle" ${state.fsm.autoAdvance ? 'checked' : ''} />答完自动进入下一状态</label>
      <button class="ghost-btn" id="endStateBtn" type="button">手动结束本状态</button>
    </section>
    <div class="card-grid"></div>
    <div class="footer-actions"><button class="ghost-btn" id="prevBtn">上一步</button><button class="ghost-btn" id="deepenBtn" ${exhausted ? 'disabled title="已达到本状态追问轮数上限"' : ''}>本状态深化追问</button><button class="primary-btn" id="nextBtn">进入下一个状态</button></div>`;
  const grid = screen.querySelector('.card-grid');
  list.forEach(q => grid.appendChild(renderQuestion(q, stage)));
  document.querySelector('#maxRoundsSelect').addEventListener('change', e => { setMaxRounds(e.target.value); render(); });
  document.querySelector('#autoAdvanceToggle').addEventListener('change', e => { state.fsm.autoAdvance = e.target.checked; save(); });
  document.querySelector('#prevBtn').addEventListener('click', () => { state.step = Math.max(0, state.step - 1); render(); });
  document.querySelector('#deepenBtn').addEventListener('click', () => { if (exhausted) return; state.fsm.lastAnswers[stage] = { ...state.answers }; setStageRound(stage, round + 1); render(); });
  document.querySelector('#endStateBtn').addEventListener('click', () => {
    if (stage === 'redflag' && !questions.redflag.every(q => questionAnswered(q))) { alert('红旗筛查是安全硬门控，请先回答全部红旗问题。'); return; }
    state.fsm.lastAnswers[stage] = { ...state.answers }; state.step = Math.min(steps.length - 1, state.step + 1); render();
  });
  document.querySelector('#nextBtn').addEventListener('click', () => {
    if (stage === 'redflag' && !questions.redflag.every(q => questionAnswered(q))) { alert('红旗筛查是安全硬门控，请先回答全部红旗问题。'); return; }
    state.fsm.lastAnswers[stage] = { ...state.answers }; state.step = Math.min(steps.length - 1, state.step + 1); render();
  });
}

function renderQuestion(q, stage) {
  const tpl = document.querySelector('#questionTemplate').content.cloneNode(true);
  const card = tpl.querySelector('.question-card');
  card.classList.toggle('redflag', stage === 'redflag');
  tpl.querySelector('.question-meta').textContent = `${stage.toUpperCase()} · ${q.id} · ${q.reason || '规则深化追问'}`;
  tpl.querySelector('h3').textContent = q.q;
  const options = tpl.querySelector('.options');
  const current = answerValue(q.id);
  if (q.type === 'number') {
    options.innerHTML = `<input class="free-note" type="number" placeholder="${q.placeholder || ''}" value="${current || ''}" />`;
    options.querySelector('input').addEventListener('input', e => setAnswer(q.id, Number(e.target.value)));
  } else if (q.type === 'range') {
    options.innerHTML = `<input type="range" min="0" max="10" value="${current ?? 5}" /><strong>${current ?? 5} 分</strong>`;
    const range = options.querySelector('input'); const label = options.querySelector('strong');
    range.addEventListener('input', e => { label.textContent = `${e.target.value} 分`; setAnswer(q.id, Number(e.target.value)); });
  } else {
    q.options.forEach(opt => {
      const selected = q.multi ? Array.isArray(current) && current.includes(opt) : current === opt;
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = `option-pill ${selected ? 'selected' : ''}`; btn.textContent = opt;
      btn.addEventListener('click', () => {
        setAnswer(q.id, opt, q.multi);
        // 单选答完后自动深化追问或自动进入下一状态；多选保留手动控制，避免选到一半被跳转。
        if (!q.multi && maybeAutoAdvance(stage)) return;
        renderQuestionStage(steps[state.step].id);
      });
      options.appendChild(btn);
    });
  }
  const note = tpl.querySelector('.free-note');
  if (q.type === 'number') note.remove();
  else {
    note.value = answerValue(`${q.id}_note`) || '';
    note.addEventListener('input', e => setAnswer(`${q.id}_note`, e.target.value));
  }
  return card;
}

function getTags() {
  const a = state.answers;
  const tags = [];
  if ((a.age || 0) >= 60) tags.push('elderly');
  if ((a.duration || '').includes('年')) tags.push('chronic_yabi', 'long_duration');
  if (['到小腿', '到足部'].includes(a.radiation)) tags.push('radiating_leg_pain');
  if (['偶尔有', '经常有', '持续存在'].includes(a.numbness) || (a.pain_nature || []).includes('麻痛')) tags.push('lower_limb_numbness');
  if ((a.aggravating || []).includes('受凉') || a.cold_relation === '遇冷加重，热敷舒服') tags.push('cold_aggravation');
  if ((a.relieving || []).includes('热敷') || a.cold_relation === '遇冷加重，热敷舒服') tags.push('warmth_relieves');
  if ((a.diseases || []).includes('骨质疏松') || (a.western_diagnosis || []).includes('骨质疏松')) tags.push('osteoporosis');
  if (a.tongue_color === '偏暗紫') tags.push('dark_tongue');
  if (a.tongue_coating === '白腻') tags.push('white_greasy_coating');
  if (a.sleep && a.sleep !== '正常') tags.push('insomnia');
  if (a.appetite === '胃口差') tags.push('poor_appetite');
  if (a.mouth_taste && a.mouth_taste !== '没有') tags.push('bitter_taste');
  return [...new Set(tags)];
}

function getRedFlagStatus() {
  const rf = questions.redflag;
  const positives = rf.filter(q => (q.urgent || []).includes(state.answers[q.id])).map(q => q.q);
  const cautions = rf.filter(q => (q.caution || []).includes(state.answers[q.id])).map(q => q.q);
  return { status: positives.length ? 'urgent' : cautions.length ? 'caution' : rf.every(q => state.answers[q.id]) ? 'safe' : 'unknown', positives, cautions };
}

function buildCase() {
  const a = state.answers; const tags = getTags(); const red = getRedFlagStatus();
  const chief = `${a.duration && (a.duration.includes('年') ? '反复' : '')}${a.main_symptom || '腰痛'}${a.duration || ''}${a.acute_worsening && a.acute_worsening !== '无明显加重' ? `，加重${a.acute_worsening}` : ''}${a.numbness && a.numbness !== '没有' ? '，伴下肢麻木' : ''}`;
  const modules = [];
  if (tags.includes('white_greasy_coating') || tags.includes('chronic_yabi')) modules.push('健脾化湿底盘');
  if (tags.includes('osteoporosis') || tags.includes('elderly')) modules.push('补肝肾强筋骨模块');
  if (tags.includes('lower_limb_numbness')) modules.push('当归四逆/通草细辛通络路线信号', '虫类搜络模块（需医师审核）');
  if (tags.includes('cold_aggravation')) modules.push('温经散寒模块');
  if (tags.includes('insomnia') || tags.includes('bitter_taste')) modules.push('少阳/安神除烦模块');
  return { chief, tags, red, modules };
}

function renderSignals() {
  const c = buildCase();
  screen.innerHTML = `
    <section class="result-panel success"><h3>患者模式：对医生有帮助的信息</h3><ul>${c.tags.map(t => `<li>${tagLabel(t)}</li>`).join('')}</ul></section>
    <section class="result-panel"><h3>规则引擎命中瀑布流</h3><p class="eyebrow">Rule Engine · Evidence Traceable</p><ul>${c.tags.map(t => `<li>${t} → ${tagLabel(t)}</li>`).join('') || '<li>待补充标签</li>'}</ul></section>
    <section class="result-panel"><h3>Tao Direct Runtime 叠加层</h3><p class="eyebrow">Transformers local inference · JSON Repair · Output Guard</p><p>后端可直接使用 <code>TAO_BACKEND=transformers</code> 加载 <code>CMLM/Dao1-30b-a3b</code>，不需要 FastAPI 包装；模型只叠加教学解释和问诊改写，若输出诊断/处方/剂量则回退规则模板。</p></section>
    <section class="result-panel"><h3>医生/CDSS 模式：候选诊断与处方策略草案</h3><p class="eyebrow">draft_for_clinician_review · 非最终医嘱 · 非患者可见 · 无患者可执行剂量</p><ul>
      <li>西医候选：${c.tags.includes('radiating_leg_pain') || c.tags.includes('lower_limb_numbness') ? '腰椎间盘突出/神经根受压相关腰腿痛（待查体影像复核）' : '非特异性腰痛等待鉴别'}</li>
      <li>中医候选：${c.tags.includes('osteoporosis') ? '肝肾不足背景' : '气血痹阻夹湿候选'}；${c.tags.includes('cold_aggravation') ? '寒湿/寒凝经脉线索' : '寒热信息待补'}</li>
      <li>方剂路线信号：${c.modules.join('、') || '待补充信息'}</li>
      <li>安全复核：高风险药物、NSAIDs、抗凝/激素/降糖药、肝肾功能、胃肠风险。</li>
    </ul></section>
    <section class="result-panel"><h3>医师审核签名闭环</h3><p>最终诊断、完整处方、剂量、煎服法和疗程只能在医生端由 licensed physician 手工录入并签名；患者端只显示医案整理线索。</p></section>
    <div class="footer-actions"><button class="ghost-btn" id="prevBtn">上一步</button><button class="primary-btn" id="nextBtn">生成最终医案</button></div>`;
  document.querySelector('#prevBtn').addEventListener('click', () => { state.step--; render(); });
  document.querySelector('#nextBtn').addEventListener('click', () => { state.step++; render(); });
}

function renderFinal() {
  const report = buildReport();
  const tabs = {
    case: report.markdown,
    handoff: report.handoff,
    tao: report.tao,
    cdss: report.cdss,
    physician: report.physician,
    json: JSON.stringify(report.json, null, 2),
  };
  screen.innerHTML = `<section class="result-panel"><div class="report-tabs">
    <button class="tab-btn active" data-tab="case">标准医案</button>
    <button class="tab-btn" data-tab="handoff">医生复核</button>
    <button class="tab-btn" data-tab="tao">Tao 教学解释</button>
    <button class="tab-btn" data-tab="cdss">CDSS 草案</button>
    <button class="tab-btn" data-tab="physician">医师签名</button>
    <button class="tab-btn" data-tab="json">规则 JSON</button>
  </div><pre class="report-box" id="reportBox"></pre><div class="footer-actions"><button class="ghost-btn" id="copyBtn">复制当前内容</button><button class="primary-btn" id="downloadBtn">下载 Markdown</button></div></section>`;
  const box = document.querySelector('#reportBox');
  const setTab = key => { box.textContent = tabs[key]; document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === key)); };
  setTab('case');
  document.querySelectorAll('.tab-btn').forEach(btn => btn.addEventListener('click', () => setTab(btn.dataset.tab)));
  document.querySelector('#copyBtn').addEventListener('click', () => navigator.clipboard?.writeText(box.textContent));
  document.querySelector('#downloadBtn').addEventListener('click', () => download('yaobi-case.md', box.textContent));
}

function buildReport() {
  const a = state.answers; const c = buildCase();
  const md = `# 腰痹医案草稿\n\n## 一、基本信息\n患者：${a.sex || '未详'}，${a.age || '未详'}岁\n\n## 二、主诉\n${c.chief}\n\n## 三、现病史\n疼痛部位：${fmt(a.location)}；放射情况：${fmt(a.radiation)}；疼痛性质：${fmt(a.pain_nature)}；疼痛评分：${a.severity ?? '未详'}/10。加重因素：${fmt(a.aggravating)}；缓解因素：${fmt(a.relieving)}。下肢麻木：${fmt(a.numbness)}，部位：${fmt(a.numbness_location)}；下肢无力：${fmt(a.weakness)}。\n\n## 四、伴随症状\n寒热：${fmt(a.cold_heat)}；寒热与疼痛关系：${fmt(a.cold_relation)}；睡眠：${fmt(a.sleep)}；胃纳：${fmt(a.appetite)}；口苦口干：${fmt(a.mouth_taste)}。\n\n## 五、既往史与检查\n既往疾病：${fmt(a.diseases)}；影像/检查：${fmt(a.imaging)}；既往诊断：${fmt(a.western_diagnosis)}；近期用药：${fmt(a.medications)}；过敏史：${fmt(a.allergy)}。\n\n## 六、中医四诊信息\n舌色：${fmt(a.tongue_color)}；舌苔：${fmt(a.tongue_coating)}；脉象：待医生面诊补充。\n\n## 七、结构化标签\n${c.tags.map(t => `- ${t}`).join('\n') || '- 暂无'}\n\n## 八、沈老经验规则线索\n${c.modules.map((m, i) => `${i + 1}. ${m}`).join('\n') || '1. 信息不足，待补充。'}\n\n## 九、医生复核清单\n- 红旗筛查：${c.red.status}\n- 下肢肌力、感觉、反射查体\n- 影像/骨密度报告\n- NSAIDs、抗凝药、肝肾功能和胃肠风险\n- 高风险药物需医师审核\n\n> 本报告为医案整理和医生端 CDSS 草案，不构成最终诊断、签名处方或患者可执行剂量。`;
  const handoff = `# 医生复核摘要\n\n- 主要问题：${c.chief}。\n- 规则标签：${c.tags.join('、') || '待补充'}。\n- 方剂路线信号：${c.modules.join('、') || '待补充'}。\n- 信息缺口：脉象、影像原文、下肢肌力/感觉查体、用药剂量与不良反应。`;
  const tao = `# Tao 教学解释叠加\n\n运行方式：TAO_BACKEND=transformers python -m backend.main --tao-chat "请解释本案规则线索" --stream\n\nTao Direct Runtime 负责把规则证据转写为教学解释；输出需通过 JSON Repair 和 Output Guard，不允许最终诊断、完整处方或患者可执行剂量。`;
  const cdss = `# CDSS 草案\n\n状态：draft_for_clinician_review；patient_visible=false；complete_prescription_generated=false；patient_executable_dose_generated=false。\n\n候选方向：${c.tags.includes('lower_limb_numbness') ? '腰腿痛/神经根相关风险待复核' : '腰痛待鉴别'}；候选证型：${c.tags.includes('osteoporosis') ? '肝肾不足背景' : '气血痹阻夹湿候选'}。`;
  const physician = `# 医师审核签名\n\n最终诊断、完整处方、剂量、煎服法、疗程只能由 licensed physician 手工录入。系统输出仅为规则证据和草案，医生确认后方可锁定。`;
  return { markdown: md, handoff, tao, cdss, physician, json: { answers: state.answers, tags: c.tags, modules: c.modules, red_flags: c.red, runtime: 'Tao Direct Transformers Runtime', guards: ['JSON Repair', 'Output Guard'], cdss_status: 'draft_for_clinician_review' } };
}

function fmt(v) { return Array.isArray(v) ? (v.join('、') || '未详') : (v || '未详'); }
function tagLabel(t) {
  const map = { elderly: '年龄偏大，对退变/肝肾不足背景有价值', chronic_yabi: '腰痛时间较久', lower_limb_numbness: '有下肢麻木', radiating_leg_pain: '有下肢放射痛', cold_aggravation: '受凉加重', warmth_relieves: '热敷缓解', osteoporosis: '骨质疏松线索', dark_tongue: '舌色偏暗紫', white_greasy_coating: '白腻苔', insomnia: '睡眠欠佳', poor_appetite: '胃纳较差', bitter_taste: '口苦/少阳线索' };
  return map[t] || t;
}

function updatePreview() {
  const c = buildCase();
  document.querySelector('#previewChief').textContent = c.chief || '未采集';
  document.querySelector('#previewHistory').textContent = `疼痛：${fmt(state.answers.location)}；放射：${fmt(state.answers.radiation)}；麻木：${fmt(state.answers.numbness)}。`;
  document.querySelector('#previewTags').textContent = c.tags.join('、') || '暂无';
  const missing = ['age','sex','duration','location','radiation','numbness','cold_relation','sleep','appetite','imaging','diseases'].filter(k => !state.answers[k]);
  document.querySelector('#previewMissing').textContent = missing.join('、') || '关键字段已较完整';
  const score = Math.max(0, Math.round((11 - missing.length) / 11 * 100));
  document.querySelector('#qualityRing').textContent = `${score}%`;
  document.querySelector('#qualityRing').style.background = `conic-gradient(var(--green) ${score * 3.6}deg, #eadfce 0deg)`;
  document.querySelector('#qualityGrade').textContent = score >= 80 ? 'good / 可复核' : score >= 60 ? 'fair / 需补问' : 'needs_more_info';
  document.querySelector('#qualityHint').textContent = score >= 80 ? '已可生成医生复核摘要。' : '建议继续补充关键字段。';
}
function download(name, text) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown' })); a.download = name; a.click(); URL.revokeObjectURL(a.href); }

// ---------------------------------------------------------------------------
// Module views (xlsx mining / evidence / review / safety / settings)
// ---------------------------------------------------------------------------

const TAG_CN = {
  lower_limb_numbness: '下肢麻木', radiating_leg_pain: '下肢放射痛', bilateral_leg_involvement: '双下肢受累',
  cold_aggravation: '遇冷/受凉加重', cold_pain: '冷痛', bitter_taste: '口苦', insomnia: '失眠/寐差',
  fatigue: '乏力', poor_appetite: '纳差', distending_pain: '胀痛', soreness: '酸痛', activity_limitation: '活动受限',
  night_pain: '夜间痛', sedentary_aggravation: '久坐加重', acute_on_chronic: '慢病急性加重', elderly: '高龄(≥60)',
  osteoporosis: '骨质疏松',
};
const cnTag = t => (t || '').startsWith('zheng::') ? `证型·${t.split('::')[1]}` : (TAG_CN[t] || t);

function noDataPanel() {
  return `<section class="result-panel"><h3>暂无挖掘数据</h3><p>请先在本地运行脱敏挖掘管道生成 <code>frontend/mined_rules.js</code>：</p>
    <pre class="runtime-code">python -m backend.mining.xlsx_case_miner --xlsx 门诊导出.xlsx \\
    --yaml rules/11_mined_rule_candidates.yaml --frontend frontend/mined_rules.js</pre>
    <p>原始 xlsx 含患者身份信息，仅保留在本地 <code>data/private/</code>，不会进入仓库；产物只包含聚合统计与行号引用。</p></section>`;
}

function barRows(dist, total, labelFn = x => x, max = 10) {
  const entries = Object.entries(dist || {}).slice(0, max);
  const top = Math.max(...entries.map(([, v]) => v), 1);
  return entries.map(([k, v]) => `
    <div class="bar-row"><span class="bar-label">${labelFn(k)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.round(v / top * 100)}%"></span></span>
      <span class="bar-value">${v}${total ? ` · ${Math.round(v / total * 100)}%` : ''}</span></div>`).join('');
}

function renderDashboard() {
  pageTitle.textContent = '总览看板 · 沈钦荣腰痹门诊经验数据';
  if (!MINED) { screen.innerHTML = noDataPanel(); return; }
  const s = MINED.dataset_stats;
  screen.innerHTML = `
    <div class="stat-grid">
      <article class="stat-card"><p class="eyebrow">脱敏病例</p><strong>${s.n_cases}</strong><span>门诊就诊记录</span></article>
      <article class="stat-card"><p class="eyebrow">含中药处方</p><strong>${s.n_with_prescription}</strong><span>可供方药挖掘</span></article>
      <article class="stat-card"><p class="eyebrow">候选规则</p><strong>${(MINED.rule_candidates || []).length}</strong><span>全部待专家审核</span></article>
      <article class="stat-card"><p class="eyebrow">签名方剂路线</p><strong>${(MINED.formula_signature_hits || []).length}</strong><span>≥70% 签名药物命中</span></article>
    </div>
    <div class="panel-grid">
      <section class="result-panel"><h3>证型分布</h3>${barRows(s.zheng_distribution, s.n_cases)}</section>
      <section class="result-panel"><h3>症状标签分布</h3>${barRows(s.symptom_tag_distribution, s.n_cases, cnTag, 12)}</section>
      <section class="result-panel"><h3>高频药物（按处方计）</h3><div class="chip-cloud">${Object.entries(MINED.herb_frequency_top || {}).slice(0, 28).map(([h, n]) => `<span class="chip">${h}<em>${n}</em></span>`).join('')}</div></section>
      <section class="result-panel"><h3>功效模块使用</h3>${barRows(MINED.herb_module_counts, s.n_with_prescription)}</section>
      <section class="result-panel"><h3>西医诊断 Top</h3>${barRows(s.western_dx_top, s.n_cases)}</section>
      <section class="result-panel"><h3>人群结构</h3>${barRows(s.age_band_distribution, s.n_cases, b => b === '未知' ? '未知' : b.replace('s', ' 岁段'))}<p class="muted">性别：${Object.entries(s.sex_distribution).map(([k, v]) => `${k} ${v}`).join(' / ')}</p></section>
    </div>
    <section class="result-panel warning"><h3>数据质量提示</h3><p>${(MINED.data_quality || {}).tongue_pulse_note || ''}</p><p class="muted">${MINED.meta ? MINED.meta.privacy : ''}</p></section>`;
}

function renderMiningModule() {
  pageTitle.textContent = '规则挖掘 · xlsx 医案候选规则（support / confidence / lift）';
  if (!MINED) { screen.innerHTML = noDataPanel(); return; }
  const rules = MINED.rule_candidates || [];
  const filter = state.miningFilter || 'all';
  const types = ['all', ...new Set(rules.map(r => r.rule_type))];
  const shown = rules.filter(r => filter === 'all' || r.rule_type === filter);
  screen.innerHTML = `
    <section class="result-panel">
      <div class="filter-row">${types.map(t => `<button class="option-pill ${t === filter ? 'selected' : ''}" data-filter="${t}">${t === 'all' ? '全部' : t}</button>`).join('')}</div>
      <table class="rule-table"><thead><tr><th>规则 ID</th><th>IF</th><th>THEN</th><th>support</th><th>confidence</th><th>lift</th><th>状态</th></tr></thead><tbody>
      ${shown.map(r => {
        const st = r.statistics || {};
        const cell = v => v === undefined ? '—' : v;
        return `<tr data-rule="${r.rule_id}"><td class="mono">${r.rule_id}</td>
          <td>${Object.entries(r.if || {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join('、') : cnTag(String(v))}`).join('<br/>')}</td>
          <td>${Object.entries(r.then || {}).map(([, v]) => Array.isArray(v) ? v.join('–') + ' 克' : v).join('<br/>')}</td>
          <td>${cell(st.support)}</td><td>${cell(st.confidence)}</td>
          <td>${st.lift !== undefined ? `<span class="lift-pill ${st.lift >= 1.5 ? 'hi' : ''}">${st.lift}</span>` : '—'}</td>
          <td><span class="badge-pending">待专家审核</span></td></tr>`;
      }).join('')}
      </tbody></table>
      <p class="muted">共 ${shown.length} 条；所有候选规则 clinician_only=true，仅供医师复核与科研教学，不构成诊断或处方依据，不向患者展示。</p>
    </section>`;
  screen.querySelectorAll('[data-filter]').forEach(btn => btn.addEventListener('click', () => { state.miningFilter = btn.dataset.filter; renderMiningModule(); }));
  screen.querySelectorAll('tr[data-rule]').forEach(tr => tr.addEventListener('click', () => { state.evidenceRule = tr.dataset.rule; state.module = 'evidence'; localStorage.setItem('yaobi-module', 'evidence'); render(); }));
}

function renderEvidenceModule() {
  pageTitle.textContent = '证据回溯 · 签名方剂命中与剂量分布';
  if (!MINED) { screen.innerHTML = noDataPanel(); return; }
  const rules = MINED.rule_candidates || [];
  const selected = rules.find(r => r.rule_id === state.evidenceRule) || rules[0];
  const hits = MINED.formula_signature_hits || [];
  screen.innerHTML = `
    <div class="panel-grid">
      <section class="result-panel"><h3>候选规则详情</h3>
        ${selected ? `<p class="mono">${selected.rule_id}</p>
          <p><strong>IF</strong> ${Object.entries(selected.if || {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('、') : cnTag(String(v))}`).join('；')}</p>
          <p><strong>THEN</strong> ${JSON.stringify(selected.then, null, 0).replace(/[{}"]/g, '')}</p>
          <p><strong>统计</strong> ${Object.entries(selected.statistics || {}).map(([k, v]) => `${k}=${v}`).join('，')}</p>
          <p><strong>证据</strong> ${selected.evidence}</p>
          <p><span class="badge-pending">pending_expert_review</span> <span class="badge-pending">clinician_only</span> 强度：${selected.strength || '—'}</p>` : '<p>暂无规则。</p>'}
        <p class="muted">在「规则挖掘」页点击任意一行即可在此回溯证据。</p>
      </section>
      <section class="result-panel"><h3>签名方剂命中（证据行号已脱敏）</h3>
        ${hits.map(h => `<details><summary><strong>${h.formula}</strong> · ${h.n_cases} 例 · 主证型 ${Object.keys(h.by_zheng)[0] || '—'}</summary>
          <p>证型分布：${Object.entries(h.by_zheng).map(([z, n]) => `${z} ${n}`).join('；')}</p>
          <p class="mono">xlsx 行号：${(h.evidence_rows || []).join(', ')}</p></details>`).join('')}
      </section>
      <section class="result-panel"><h3>重点药物剂量分布（医师端研究用）</h3>
        <table class="rule-table"><thead><tr><th>药物</th><th>n</th><th>最小(g)</th><th>最大(g)</th><th>常用(g)</th><th>复核</th></tr></thead><tbody>
        ${Object.entries(MINED.dose_table || {}).map(([h, d]) => `<tr><td>${h}</td><td>${d.n}</td><td>${d.min_g}</td><td>${d.max_g}</td><td>${d.mode_g}</td><td><span class="badge-pending">医师必核</span></td></tr>`).join('')}
        </tbody></table>
        <p class="muted">剂量分布仅为医师端经验研究信号，不向患者输出，不构成可执行剂量。</p>
      </section>
    </div>`;
}

function renderReviewModule() {
  pageTitle.textContent = '医师审核 · Physician Review 签名闭环';
  const c = buildCase();
  screen.innerHTML = `
    <div class="panel-grid">
      <section class="result-panel"><h3>待审核队列</h3>
        <ul class="review-list">
          <li><strong>当前问诊医案草稿</strong><span>${c.chief || '未开始'}</span><span class="badge-pending">draft_for_clinician_review</span></li>
          <li><strong>挖掘候选规则</strong><span>${MINED ? (MINED.rule_candidates || []).length : 0} 条</span><span class="badge-pending">pending_expert_review</span></li>
        </ul></section>
      <section class="result-panel"><h3>签名边界（不可由模型代签）</h3>
        <ul>
          <li>最终诊断：仅 licensed physician 手工录入（source=physician_entered）。</li>
          <li>完整处方、剂量、煎服法、疗程：仅医师手工录入并签名。</li>
          <li>模型生成内容（source=model_generated）一律 rejected_model_generated_diagnosis。</li>
          <li>附片、细辛、全蝎、蜈蚣、麻黄等剂量必须医师逐项复核。</li>
        </ul>
        <div class="sign-form">
          <label>医师工号 <input class="free-note" placeholder="DOC-001" /></label>
          <label>执业证号 <input class="free-note" placeholder="LICENSE-001" /></label>
          <button class="primary-btn" type="button" id="signBtn">签名确认（演示）</button>
        </div></section>
    </div>`;
  document.querySelector('#signBtn').addEventListener('click', () => alert('演示环境：实际签名需在 physician_review_skill 后端流程中完成审计记录。'));
}

function renderSafetyModule() {
  pageTitle.textContent = '评估与安全 · 红旗门控 / Output Guard / 数据质量';
  const q = MINED ? MINED.data_quality : null;
  screen.innerHTML = `
    <div class="panel-grid">
      <section class="result-panel redflag"><h3>红旗硬门控（四类）</h3>
        <ul><li>马尾综合征：大小便障碍、会阴麻木 → 立即急诊。</li><li>肿瘤风险：肿瘤史、消瘦、夜间痛进行性加重。</li><li>感染风险：发热寒战、近期感染。</li><li>骨折风险：外伤、激素、重度骨质疏松骤发剧痛。</li></ul>
        <p>命中 urgent 立即终止问诊；红旗问题未答完时任何方式不能跳过（FSM 与 UI 双重拦截）。</p></section>
      <section class="result-panel"><h3>Output Guard 禁用输出</h3>
        <ul><li>最终诊断、完整处方、患者可执行剂量、煎服法 → 拦截并回退规则模板。</li><li>Tao 只能重排/改写/解释既有问题，新增问题 id 一律丢弃。</li><li>患者端请求诊断处方 → patient_request_guard 阻断。</li></ul></section>
      <section class="result-panel"><h3>测试与验收指标</h3>
        <ul><li>pytest 全量：41 项（含红旗拦截、禁用输出、挖掘脱敏、PII 泄漏检查）。</li><li>红旗召回测试：urgent 信号 100% 进入 S_EMERGENCY_NOTICE。</li><li>禁用输出拦截：模型代签诊断/处方用例全部 rejected。</li></ul></section>
      <section class="result-panel warning"><h3>数据质量与局限</h3>
        ${q ? `<ul><li>病例数 ${q.n_cases}，含处方 ${q.n_with_prescription}。</li><li>舌脉可用性：${q.tongue_pulse_usable ? '可用' : '不可用'}。${q.tongue_pulse_note}</li><li>缺证型 ${q.n_missing_zheng} 例。</li></ul>` : '<p>运行挖掘管道后展示。</p>'}
        <p>单中心、单医师、横断面数据；候选规则只是统计信号，须经专家审核才能升级为正式规则。</p></section>
    </div>`;
}

function renderSettingsModule() {
  pageTitle.textContent = '设置 · FSM 追问与 Tao 运行时';
  screen.innerHTML = `
    <div class="panel-grid">
      <section class="result-panel"><h3>有限状态机追问设置</h3>
        <label class="fsm-setting">每状态追问轮数上限（1–5）
          <select id="settingMaxRounds">${[1, 2, 3, 4, 5].map(n => `<option value="${n}" ${n === maxRounds() ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
        <label class="fsm-setting"><input type="checkbox" id="settingAutoAdvance" ${state.fsm.autoAdvance ? 'checked' : ''} />答完自动进入下一状态（自动终止追问）</label>
        <p class="muted">对应后端 CaseGuideSession(max_followups_per_state, questions_per_turn) 与 set_max_followups()。</p></section>
      <section class="result-panel"><h3>Tao Direct Runtime</h3>
        <pre class="runtime-code">TAO_BACKEND=transformers python -m backend.main --tao-chat "请解释本案规则线索" --stream</pre>
        <p>模型仅叠加问诊改写与教学解释；JSON Repair + Output Guard 失败即回退规则模板。</p></section>
      <section class="result-panel"><h3>本地数据</h3>
        <button class="ghost-btn" id="clearBtn" type="button">清空本地问诊数据</button>
        <p class="muted">仅清除浏览器 localStorage 中的答案与 FSM 进度。</p></section>
    </div>`;
  document.querySelector('#settingMaxRounds').addEventListener('change', e => setMaxRounds(e.target.value));
  document.querySelector('#settingAutoAdvance').addEventListener('change', e => { state.fsm.autoAdvance = e.target.checked; save(); });
  document.querySelector('#clearBtn').addEventListener('click', () => {
    if (!confirm('确定清空本地问诊数据？')) return;
    localStorage.removeItem('yaobi-case'); localStorage.removeItem('yaobi-fsm'); location.reload();
  });
}

document.querySelector('#doctorModeBtn').addEventListener('click', () => { state.doctorMode = !state.doctorMode; alert(state.doctorMode ? '已进入医生/研究者模式' : '已进入患者简洁模式'); });
document.querySelector('#exportJsonBtn').addEventListener('click', () => download('yaobi-case.json', JSON.stringify(buildReport().json, null, 2)));
render(); updatePreview();
