import { FormEvent, useEffect, useState } from 'react';

type Agent = { id: string; agent: string; status: string; output?: Record<string, any>; error?: string; duration_ms?: number };
type Run = { id: string; status: string; provider: string; model: string; plan?: Record<string, any>; conflicts: Record<string, any>[]; agents: Agent[] };
type Proposal = { id: string; status: string; parameter: string; proposed_value: string | number; sample_count: number; confidence: string; rationale: string };
type Runtime = { provider: string; provider_label: string; model: string; mode: string; api_key_configured: boolean; api_key_hint: string | null };
const names: Record<string, string> = { quality: '数据质检 Agent', recovery: '恢复 Agent', training: '训练 Agent', fat_loss: '减脂 Agent', review: '冲突复核 Agent', coach: '总教练 Agent', risk: '风险审核 Agent' };
const statusNames: Record<string, string> = { queued: '排队中', running: '运行中', succeeded: '已完成', completed: '已完成', failed: '失败', idle: '等待提交', 'no conflict': '无冲突跳过', waiting: '等待中' };
const providerNames: Record<string, string> = { openai_compatible: '阿里云百炼', ollama: 'Ollama', fake: '模拟 Provider' };
const statusLabel = (value?: string) => value ? (statusNames[value] || value) : '';
const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

export default function App() {
  const [runtime, setRuntime] = useState<Runtime>({ provider: 'checking', provider_label: '', model: '', mode: '', api_key_configured: false, api_key_hint: null });
  const [profile, setProfile] = useState({ experience: 'beginner', weekly_days: 3, session_minutes: 60, limitations: '', preferences: '' });
  const [entry, setEntry] = useState({ date: today(), energy: 3, fatigue: 2, sleep_hours: '', weight_kg: '', completion: 'none', completion_pct: 100, did_train: false, rpe: '', pain: false, notes: '' });
  const [exercise, setExercise] = useState({ name: '', sets: 3, reps: 8, load_kg: '' });
  const [run, setRun] = useState<Run | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [report, setReport] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetch('/api/v1/system/runtime').then(r => r.json()).then(setRuntime).catch(() => setRuntime({ provider: 'unavailable', provider_label: '', model: '', mode: 'unavailable', api_key_configured: false, api_key_hint: null }));
    fetch('/api/v1/profile').then(r => r.json()).then(r => r.data && Object.keys(r.data).length && setProfile(current => ({ ...current, ...r.data }))).catch(() => {});
    refreshInsights();
  }, []);

  async function refreshInsights() {
    const [learning, weekly] = await Promise.all([
      fetch('/api/v1/learning-proposals').catch(() => null),
      fetch('/api/v1/reports/weekly/latest').catch(() => null),
    ]);
    if (learning?.ok) setProposals(await learning.json());
    if (weekly?.ok) setReport(await weekly.json());
  }

  async function decideProposal(id: string, action: 'approve' | 'reject') {
    const response = await fetch(`/api/v1/learning-proposals/${id}/${action}`, { method: 'POST' });
    if (!response.ok) { const body = await response.json(); setMessage(body.detail || '学习提案处理失败'); return; }
    await refreshInsights(); setMessage(action === 'approve' ? '学习提案已应用并创建画像版本。' : '学习提案已驳回。');
  }

  async function saveProfile() {
    const response = await fetch('/api/v1/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(profile) });
    if (!response.ok) throw new Error('个人档案保存失败');
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setRun(null); setMessage('正在保存记录并启动独立 Agent 分析…');
    try {
      await saveProfile();
      const payload = { ...entry, energy: Number(entry.energy), fatigue: Number(entry.fatigue), sleep_hours: entry.sleep_hours === '' ? null : Number(entry.sleep_hours), weight_kg: entry.weight_kg === '' ? null : Number(entry.weight_kg), completion_pct: Number(entry.completion_pct), rpe: entry.rpe === '' ? null : Number(entry.rpe), exercises: entry.did_train && exercise.name.trim() ? [{ name: exercise.name.trim(), sets: Number(exercise.sets), reps: Number(exercise.reps), load_kg: exercise.load_kg === '' ? null : Number(exercise.load_kg) }] : [] };
      const saved = await fetch('/api/v1/check-ins', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const checkin = await saved.json(); if (!saved.ok) throw new Error(checkin.detail || '记录保存失败');
      const queued = await fetch(`/api/v1/planning-runs?checkin_id=${checkin.id}`, { method: 'POST' });
      const created = await queued.json(); if (!queued.ok) throw new Error(created.detail || 'Agent 运行启动失败');
      setRun({ id: created.id, status: created.status, provider: runtime.provider, model: runtime.model, conflicts: [], agents: [] });
      setMessage('运行已排队，追踪每个 Agent 的独立调用。');
      const events = new EventSource(`/api/v1/planning-runs/${created.id}/events`);
      events.addEventListener('agent', e => { const agent = JSON.parse((e as MessageEvent).data) as Agent; setRun(current => current ? { ...current, agents: [...current.agents.filter(a => a.id !== agent.id), agent] } : current); });
      events.addEventListener('run', e => { const state = JSON.parse((e as MessageEvent).data); setRun(current => current ? { ...current, status: state.status, plan: state.plan } : current); if (['completed', 'failed'].includes(state.status)) { events.close(); setBusy(false); refreshInsights(); setMessage(state.status === 'completed' ? '本次 Agent 协作完成。' : `运行失败：${state.error || '请检查服务状态'}`); } });
      events.onerror = () => { events.close(); setBusy(false); setMessage('运行流暂时中断；可以通过运行详情接口检查持久化状态。'); };
    } catch (error) { setBusy(false); setMessage(error instanceof Error ? error.message : '请求失败'); }
  }

  const cloudMissingKey = runtime.mode === 'live-cloud' && !runtime.api_key_configured;
  const runtimeLabel = runtime.mode === 'simulated' ? '模拟推理' : runtime.mode === 'live-local' ? '本地真实推理' : runtime.mode === 'live-cloud' ? '云端真实推理' : runtime.mode === 'unavailable' ? 'API 不可用' : '服务检查中';
  const runtimeDetail = runtime.mode === 'live-cloud' ? `${runtime.provider_label} · ${runtime.model} · ${cloudMissingKey ? 'API KEY 未配置' : runtime.api_key_hint ? `API KEY ${runtime.api_key_hint}` : 'API KEY 已配置'}` : runtime.mode === 'live-local' ? `Ollama · ${runtime.model}` : runtime.mode === 'simulated' ? '确定性规则 · 无模型调用' : '';
  const privacyLabel = runtime.mode === 'live-cloud' ? '云端推理 · 健身上下文发送至百炼' : '本机运行 · 无云端模型传输';
  return <div className="shell">
    <aside className="rail"><div className="brand"><b>F</b><span>FORM<small>AGENT TRAINING</small></span></div><div className="rail-label">WORKSPACE</div><a className="rail-link selected"><i>01</i>今日工作台</a><a className="rail-link"><i>02</i>运行追踪</a><a className="rail-link"><i>03</i>学习画像</a><div className="rail-bottom"><span className={`local-dot ${runtime.mode === 'live-cloud' ? 'cloud' : ''}`}/>{privacyLabel}</div></aside>
    <main><header className="top"><span>PERSONAL SYSTEM <b>/</b> AGENT ORCHESTRATION</span><div className={`provider ${cloudMissingKey ? 'provider-warning' : ''}`}><span className={`local-dot ${runtime.mode === 'live-cloud' ? 'cloud' : ''}`}/><div><strong>{runtimeLabel}</strong>{runtimeDetail && <small>{runtimeDetail}</small>}</div></div></header>
      <section className="intro"><div><small>FITNESS DECISION SUPPORT</small><h1>训练工作台</h1><p>每日记录驱动独立 Agent 分析、冲突复核与证据化训练调整。</p></div><div className="model-stamp"><strong>07</strong><span>INDEPENDENT<br/>AGENTS</span></div></section>
      <div className="workspace">
        <form className="panel log-panel" onSubmit={submit}><div className="panel-head"><div><small>01 / INPUT</small><h2>每日状态记录</h2></div><span>手动录入</span></div>
          <label>记录日期<input type="date" max={today()} value={entry.date} onChange={e => setEntry({ ...entry, date: e.target.value })}/></label>
          <div className="field-grid"><label>精力<select value={entry.energy} onChange={e => setEntry({ ...entry, energy: Number(e.target.value) })}>{[1,2,3,4,5].map(x => <option key={x} value={x}>{x} / 5</option>)}</select></label><label>酸痛 / 疲劳<select value={entry.fatigue} onChange={e => setEntry({ ...entry, fatigue: Number(e.target.value) })}>{[1,2,3,4,5].map(x => <option key={x} value={x}>{x} / 5</option>)}</select></label><label>睡眠小时<input type="number" min="0" max="24" step="0.25" value={entry.sleep_hours} onChange={e => setEntry({ ...entry, sleep_hours: e.target.value })} placeholder="选填"/></label><label>体重 kg<input type="number" min="25" max="300" step="0.1" value={entry.weight_kg} onChange={e => setEntry({ ...entry, weight_kg: e.target.value })} placeholder="选填"/></label></div>
          <label>上一计划完成<select value={entry.completion} onChange={e => setEntry({ ...entry, completion: e.target.value })}><option value="none">暂无计划 / 休息日</option><option value="full">按计划完成</option><option value="partial">部分完成</option><option value="missed">未完成</option></select></label>
          <div className="field-grid"><label>完成度 %<input type="number" min="0" max="100" value={entry.completion_pct} onChange={e => setEntry({ ...entry, completion_pct: Number(e.target.value) })}/></label><label>训练 RPE<select value={entry.rpe} onChange={e => setEntry({ ...entry, rpe: e.target.value })}><option value="">未训练</option>{[6,7,8,9,10].map(x => <option key={x} value={x}>{x} / 10</option>)}</select></label></div>
          <label className="check"><input type="checkbox" checked={entry.did_train} onChange={e => setEntry({ ...entry, did_train: e.target.checked })}/>今天进行了训练</label>
          {entry.did_train && <div className="exercise-input"><small>ACTUAL EXERCISE</small><div className="field-grid"><label>动作<input value={exercise.name} onChange={e => setExercise({ ...exercise, name: e.target.value })} placeholder="例如：腿举"/></label><label>重量 kg<input type="number" min="0" step="0.5" value={exercise.load_kg} onChange={e => setExercise({ ...exercise, load_kg: e.target.value })} placeholder="选填"/></label><label>组数<input type="number" min="1" max="20" value={exercise.sets} onChange={e => setExercise({ ...exercise, sets: Number(e.target.value) })}/></label><label>次数<input type="number" min="1" max="100" value={exercise.reps} onChange={e => setExercise({ ...exercise, reps: Number(e.target.value) })}/></label></div></div>}
          <label className="check warning"><input type="checkbox" checked={entry.pain} onChange={e => setEntry({ ...entry, pain: e.target.checked })}/>有疼痛或异常不适 <small>安全规则优先处理</small></label>
          <label>备注<textarea rows={3} maxLength={2000} value={entry.notes} onChange={e => setEntry({ ...entry, notes: e.target.value })} placeholder="训练变化、疼痛位置或恢复备注"/></label>
          <div className="section-line"/><div className="panel-head"><div><small>PROFILE / CONSTRAINTS</small><h2>训练设置</h2></div></div>
          <div className="field-grid"><label>训练经验<select value={profile.experience} onChange={e => setProfile({ ...profile, experience: e.target.value })}><option value="beginner">初学</option><option value="intermediate">规律训练</option><option value="advanced">长期训练</option></select></label><label>每周训练天数<input type="number" min="1" max="7" value={profile.weekly_days} onChange={e => setProfile({ ...profile, weekly_days: Number(e.target.value) })}/></label></div>
          <label>动作限制<textarea rows={2} value={profile.limitations} onChange={e => setProfile({ ...profile, limitations: e.target.value })} placeholder="例如：膝部限制、避开某动作"/></label>
          <button className="primary" disabled={busy}>{busy ? 'Agent 运行中…' : '保存并运行 Agent 工作流'} <b>→</b></button><p className="form-status">{message}</p>
        </form>

        <div className="right-stack"><section className="panel run-panel"><div className="panel-head"><div><small>02 / LIVE EXECUTION</small><h2>Agent 运行追踪</h2></div><span className={`run-status ${run?.status || 'idle'}`}>{statusLabel(run?.status || 'idle')}</span></div>
          {!run && <div className="empty">提交状态后，这里会显示各 Agent 的独立调用、冲突复核和最终审核。</div>}
          {run && <><div className="run-meta"><span>运行 ID <b>{run.id.slice(0, 8)}</b></span><span>{providerNames[run.provider] || run.provider} / {run.model}</span></div><div className="timeline">{['quality','recovery','training','fat_loss','review','coach','risk','learning'].map((key, i) => { const agent = run.agents.find(a => a.agent === key); const skipped = key === 'review' && !run.agents.some(a => a.agent === 'review') && run.status === 'completed'; const state = agent?.status || (skipped ? 'no conflict' : 'queued'); return <article className={`agent-row ${agent?.status || (skipped ? 'skipped' : 'waiting')}`} key={key}><div className="node"><span>{String(i + 1).padStart(2,'0')}</span></div><div className="agent-copy"><div className="agent-title"><strong>{names[key] || '学习 Agent'}</strong><span>{statusLabel(state)}</span></div>{agent?.output && <><p>{agent.output.rationale || agent.output.summary || agent.output.decision}</p><details><summary>结构化输出与证据</summary><pre>{JSON.stringify(agent.output, null, 2)}</pre></details></>}{agent?.error && <p className="error">{agent.error}</p>}</div><small className="duration">{agent?.duration_ms != null ? `${agent.duration_ms} ms` : ''}</small></article>; })}</div>
          {run.plan && <div className="final-plan"><small>FINAL / RISK-GATED PLAN</small><h3>{run.plan.title}</h3><p>{run.plan.summary}</p><div className="exercise-list">{(run.plan.exercises || []).map((exercise: any, i: number) => <div className="exercise" key={i}><b>{exercise.name}</b><span>{exercise.sets} × {exercise.reps}{exercise.load_kg ? ` · ${exercise.load_kg} kg` : ''}</span></div>)}</div><span className={`decision ${run.plan.status}`}>{run.plan.status}</span></div>}</>}
        </section>
          <section className="panel architecture-panel"><div className="panel-head"><div><small>ORCHESTRATION</small><h2>协作机制</h2></div><span className="langgraph">LANGGRAPH</span></div><div className="flow-strip"><span>QUALITY</span><b>→</b><span>PARALLEL SPECIALISTS</span><b>→</b><span>CONFLICT REVIEW</span><b>→</b><span>COACH</span><b>→</b><span>RISK GATE</span></div><p>Agent 任务各自独立调用模型并保存运行记录。当前推理并发限制为 1，兼顾本地显存和云端限流；冲突复核最多一轮。</p></section>
          <section className="panel learning-panel"><div className="panel-head"><div><small>FEEDBACK LOOP</small><h2>自主学习与周报</h2></div><span className="version">VERSIONED</span></div>{report && <><div className="weekly-strip"><span><b>{report.sessions}</b> 本周训练</span><span><b>{report.adherence_pct ?? '--'}%</b> 执行率</span><span><b>{report.median_rpe ?? '--'}</b> 中位 RPE</span><span><b>{report.weight_sample_count}</b> 体重样本</span></div><div className="weekly-advice"><b>本周建议 · {report.confidence === 'medium' ? '中等置信度' : '低置信度'}</b><ul>{(report.recommendations || []).map((item: string, index: number) => <li key={index}>{item}</li>)}</ul></div></>}{proposals.length ? proposals.slice(0,3).map(p => <div className="proposal" key={p.id}><div><b>{p.parameter} → {String(p.proposed_value)}</b><small>{p.rationale} · 样本 {p.sample_count} · {p.confidence}</small></div><span className={`proposal-state ${p.status}`}>{p.status}</span>{p.status === 'pending' && <div className="proposal-actions"><button type="button" onClick={() => decideProposal(p.id,'approve')}>应用</button><button type="button" onClick={() => decideProposal(p.id,'reject')}>驳回</button></div>}</div>) : <div className="callout">完成并记录训练动作后，Learning Agent 会在这里提交带证据的画像更新。</div>}<div className="callout">低风险提案满足阈值后自动应用；高影响变更须确认。模型不能修改提示词和安全策略。</div></section>
        </div>
      </div>
      <footer>FORM / PERSONAL FITNESS AGENT PLATFORM <span>本地编排 · 模型建议需由本人判断</span></footer>
    </main>
  </div>;
}
