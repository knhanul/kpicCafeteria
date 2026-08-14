const state = {
  view: 'workspace', mode: 'meal', focus: false, weeks: 2,
  weekStart: mondayOf(new Date()), workspace: null,
  selectedServiceId: null, selectedService: null, selectedMenuItemId: null,
  stats: null, dashboard: null, importToken: null, masterTab: 'menus', masterSelectionId: null,
  masterDataTab: 'hwpx-templates', masterDataSelectionId: null, mealDefaults: null,
  mealServiceTime: null, preservationCollectionTime: null,
  mealEditorDraft: null, mealEditorDirty: false,
  menuSearchOpen: false, menuSearchQuery: '',
  menuPickerDraft: null,
  codes: null, ingredientCache: [], selectedRecipeId: null,
  documentPreview: null,
};

const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];

function mondayOf(value) {
  const d = new Date(value); d.setHours(12,0,0,0);
  const day = d.getDay(); const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff); return d;
}
function addDays(value, count) { const d = new Date(value); d.setDate(d.getDate()+count); return d; }
function isoDate(value) { return new Date(value).toISOString().slice(0,10); }
function koDate(value) { return new Intl.DateTimeFormat('ko-KR',{month:'2-digit',day:'2-digit'}).format(new Date(value)); }
function dateTimeLocal(value) { return value ? new Date(value).toISOString().slice(0,16) : ''; }
function escapeHtml(value='') { return String(value).replace(/[&<>'"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function numberText(value) { return value === null || value === undefined || value === '' ? '' : Number(value).toLocaleString('ko-KR',{maximumFractionDigits:2}); }
function compactPeriodLabel(startIso, endIso) {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const y1 = start.getFullYear();
  const y2 = end.getFullYear();
  const m1 = String(start.getMonth() + 1).padStart(2, '0');
  const m2 = String(end.getMonth() + 1).padStart(2, '0');
  const d1 = String(start.getDate()).padStart(2, '0');
  const d2 = String(end.getDate()).padStart(2, '0');
  const left = `${y1}.${m1}.${d1}`;
  const right = y1 === y2 ? `${m2}.${d2}` : `${y2}.${m2}.${d2}`;
  return `${left} ~ ${right}`;
}

const DOCUMENT_PREVIEW_CONFIG = {
  MEAL_PLAN: { label: '식단표', hwpxUrl: '/api/documents/meal-plan/hwpx' },
  COOKING_INSTRUCTION: { label: '조리지시서', hwpxUrl: '/api/documents/cooking-instruction/hwpx' },
  PRESERVATION_RECORD: { label: '보존식 기록지', hwpxUrl: '/api/documents/preserved-food/hwpx' },
};
const DOCUMENT_PREVIEW_ORDER = ['MEAL_PLAN', 'COOKING_INSTRUCTION', 'PRESERVATION_RECORD'];

function documentPreviewLabel(type) {
  return DOCUMENT_PREVIEW_CONFIG[type]?.label || '문서';
}

function documentPreviewFilename(type, startDate, endDate, extension) {
  const name = documentPreviewLabel(type).replace(/\s+/g, '');
  return `${name}_${String(startDate).replaceAll('-', '')}_${String(endDate).replaceAll('-', '')}.${extension}`;
}

function parseContentDispositionFilename(header, fallback) {
  if (!header) return fallback;
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8) {
    try { return decodeURIComponent(utf8[1]); } catch { /* ignore */ }
  }
  const ascii = header.match(/filename="?([^";]+)"?/i);
  return ascii ? ascii[1] : fallback;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function triggerDownloadFromUrl(blobUrl, filename) {
  const anchor = document.createElement('a');
  anchor.href = blobUrl;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

async function requestBinary(url, options={}) {
  try {
    const response = await fetch(url, options);
    if (response.status === 401) { location.href='/login'; throw new Error('로그인이 필요합니다.'); }
    if (!response.ok) {
      const type = response.headers.get('content-type') || '';
      const data = type.includes('application/json') ? await response.json() : await response.text();
      throw new Error(data.detail || data || `요청 실패 (${response.status})`);
    }
    return response;
  } catch (error) {
    if (error instanceof TypeError) throw new Error('네트워크 오류가 발생했습니다.');
    throw error;
  }
}

async function api(url, options={}) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.href='/login'; throw new Error('로그인이 필요합니다.'); }
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.detail || data || `요청 실패 (${response.status})`);
  return data;
}
function json(method, body) { return {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}; }

function classifyDocumentPreviewError(message='') {
  const text = String(message || '');
  if (text.includes('출력할 배식이 없습니다')) {
    return { kind: 'no_data', title: '데이터가 없습니다.', detail: '출력할 배식이 없습니다.' };
  }
  if (text.includes('활성 HWPX 템플릿이 없습니다')) {
    return { kind: 'template_missing', title: 'HWPX 템플릿이 없습니다.', detail: text };
  }
  if (text.includes('HWPX 생성에 실패했습니다')) {
    return { kind: 'hwpx_generation', title: 'HWPX 생성 실패', detail: 'HWPX 파일 생성에 실패했습니다.' };
  }
  if (text.includes('PDF 생성에 실패했습니다') || text.includes('HWPX를 PDF로 변환하지 못했습니다') || text.includes('PDF 저장 중 오류')) {
    return { kind: 'pdf_conversion', title: '미리보기를 생성하지 못했습니다.', detail: '미리보기를 생성하지 못했습니다. HWPX 파일은 다운로드할 수 있습니다.' };
  }
  if (text.includes('네트워크 오류')) {
    return { kind: 'network', title: '네트워크 오류', detail: '네트워크 오류가 발생했습니다.' };
  }
  return { kind: 'unknown', title: '미리보기를 생성하지 못했습니다.', detail: text || '미리보기를 생성하지 못했습니다.' };
}

function cleanupDocumentPreview() {
  state.documentPreview = null;
}

function syncDocumentPreviewRangeFromInputs() {
  const preview = state.documentPreview;
  if (!preview) return null;
  const start = $('#document-preview-start')?.value;
  const end = $('#document-preview-end')?.value;
  if (start) preview.startDate = start;
  if (end) preview.endDate = end;
  return preview;
}

function openDocumentPreviewDialog() {
  const initialType = { meal: 'MEAL_PLAN', cooking: 'COOKING_INSTRUCTION', preservation: 'PRESERVATION_RECORD' }[state.mode] || 'MEAL_PLAN';
  const rangeStart = state.workspace?.start;
  const rangeEnd = state.workspace?.end;
  if (!rangeStart || !rangeEnd) {
    toast('출력 기간을 불러오지 못했습니다.', true);
    return;
  }
  cleanupDocumentPreview();
  state.documentPreview = {
    type: initialType,
    startDate: rangeStart,
    endDate: rangeEnd,
    hwpxFilename: documentPreviewFilename(initialType, rangeStart, rangeEnd, 'hwpx'),
  };
  renderDocumentPreviewDialog();
}

function renderDocumentPreviewDialog() {
  const preview = state.documentPreview;
  if (!preview) return;
  const title = `${documentPreviewLabel(preview.type)} 출력`;
  const tabs = DOCUMENT_PREVIEW_ORDER.map(type => `<button type="button" class="secondary-button${preview.type===type?' active':''}" data-preview-type="${type}">${escapeHtml(documentPreviewLabel(type))}</button>`).join('');
  modal(`<div class="modal-head document-preview-head"><div><h3 id="document-preview-title">${escapeHtml(title)}</h3><small>${escapeHtml(preview.startDate)} ~ ${escapeHtml(preview.endDate)}</small></div><button class="icon-button" id="document-preview-close" aria-label="닫기">×</button></div><div class="preview-type-tabs" id="document-preview-types">${tabs}</div><div class="preview-range-form"><label class="field"><span>시작일</span><input id="document-preview-start" type="date" value="${escapeHtml(preview.startDate)}"></label><label class="field"><span>종료일</span><input id="document-preview-end" type="date" value="${escapeHtml(preview.endDate)}"></label></div><div class="button-row preview-action-row"><button class="primary-button" id="document-preview-hwpx" type="button">HWPX 다운로드</button></div>`);
  bindDocumentPreviewDialogEvents();
}

function bindDocumentPreviewDialogEvents() {
  const preview = state.documentPreview;
  if (!preview) return;
  $('#document-preview-close')?.addEventListener('click', closeModal);
  $$('#document-preview-types [data-preview-type]').forEach(button => {
    button.addEventListener('click', () => {
      if (!state.documentPreview) return;
      const nextType = button.dataset.previewType;
      if (state.documentPreview.type === nextType) return;
      state.documentPreview.type = nextType;
      state.documentPreview.hwpxFilename = documentPreviewFilename(nextType, state.documentPreview.startDate, state.documentPreview.endDate, 'hwpx');
      renderDocumentPreviewDialog();
    });
  });
  $('#document-preview-hwpx')?.addEventListener('click', downloadDocumentPreviewHwpx);
}

async function downloadDocumentPreviewHwpx() {
  const preview = syncDocumentPreviewRangeFromInputs();
  if (!preview) return;
  const config = DOCUMENT_PREVIEW_CONFIG[preview.type];
  if (!config) return;
  try {
    const response = await requestBinary(config.hwpxUrl, json('POST', { start_date: preview.startDate, end_date: preview.endDate }));
    const blob = await response.blob();
    const filename = parseContentDispositionFilename(response.headers.get('content-disposition'), documentPreviewFilename(preview.type, preview.startDate, preview.endDate, 'hwpx'));
    triggerDownload(blob, filename);
    toast('HWPX 파일을 다운로드했습니다.');
  } catch (error) {
    toast(error.message, true);
  }
}

function toast(message, error=false) {
  const node = document.createElement('div'); node.className=`toast${error?' error':''}`; node.textContent=message;
  $('#toast-root').append(node); setTimeout(()=>node.remove(),3200);
}
function modal(content) {
  $('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal">${content}</section></div>`;
  $('.modal-backdrop').addEventListener('click',e=>{if(e.target.classList.contains('modal-backdrop')) closeModal();});
}
function closeModal(){
  cleanupDocumentPreview();
  $('#modal-root').innerHTML='';
}

function normalizeTime24(rawValue) {
  const trimmed = String(rawValue).trim();
  if (!trimmed) return null;
  const hms = trimmed.match(/^(\d{1,2}):(\d{1,2}):(\d{1,2})$/);
  if (hms) { const h=Number(hms[1]),m=Number(hms[2]); if(h>=0&&h<=23&&m>=0&&m<=59) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`; return null; }
  const separated = trimmed.match(/^(\d{1,2})\D+(\d{1,2})$/);
  let hour, minute;
  if (separated) { hour = Number(separated[1]); minute = Number(separated[2]); }
  else {
    const digits = trimmed.replace(/\D/g, '');
    if (digits.length === 0 || digits.length > 4) return null;
    if (digits.length <= 2) { hour = Number(digits); minute = 0; }
    else if (digits.length === 3) { hour = Number(digits.slice(0,1)); minute = Number(digits.slice(1)); }
    else { hour = Number(digits.slice(0,2)); minute = Number(digits.slice(2,4)); }
  }
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return `${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')}`;
}

function addMinutes(time, delta) {
  const normalized = normalizeTime24(time);
  if (!normalized) throw new Error('Invalid time');
  const [hour, minute] = normalized.split(':').map(Number);
  const total = (hour * 60 + minute + delta + 1440) % 1440;
  return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
}

function createTimeInput24({value, onChange, stepMinutes=5, disabled=false, required=false, label='', showQuickButtons=true}) {
  const id = 'ti24-' + Math.random().toString(36).slice(2,9);
  const initial = normalizeTime24(value) || '';
  const quickBtns = showQuickButtons ? `<button type="button" class="ti24-quick" data-delta="-${stepMinutes}" aria-label="${label||'시간'} ${stepMinutes}분 감소" tabindex="-1">-${stepMinutes}분</button><button type="button" class="ti24-quick" data-delta="${stepMinutes}" aria-label="${label||'시간'} ${stepMinutes}분 증가" tabindex="-1">+${stepMinutes}분</button>` : '';
  const html = `<div class="ti24-wrap"${disabled?' data-disabled':''}><input type="text" inputmode="numeric" autocomplete="off" maxlength="5" placeholder="HH:mm" class="ti24-input" id="${id}" value="${initial}"${disabled?' disabled':''}${required?' required':''} aria-invalid="false" /><div class="ti24-btns">${quickBtns}</div></div>`;
  const tmp = document.createElement('div'); tmp.innerHTML = html; const el = tmp.firstElementChild;
  const input = el.querySelector('input');
  let lastValid = initial;
  function commit() {
    const raw = input.value;
    const normalized = normalizeTime24(raw);
    if (normalized === null) {
      if (raw.trim() === '' && !required) { input.value=''; input.setAttribute('aria-invalid','false'); lastValid=''; onChange(null); return; }
      input.value = lastValid; input.setAttribute('aria-invalid','true'); input.focus();
      toast('00:00부터 23:59 사이의 시간을 입력해 주세요.', true);
      return;
    }
    input.value = normalized; input.setAttribute('aria-invalid','false'); lastValid = normalized; onChange(normalized);
  }
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    else if (e.key === 'Escape') { e.preventDefault(); input.value = lastValid; input.setAttribute('aria-invalid','false'); input.blur(); }
    else if (e.key === 'ArrowUp') { e.preventDefault();
      if (!lastValid) return;
      const delta = e.shiftKey ? stepMinutes*2 : stepMinutes;
      const newVal = addMinutes(lastValid, delta); input.value = newVal; lastValid = newVal; onChange(newVal);
    } else if (e.key === 'ArrowDown') { e.preventDefault();
      if (!lastValid) return;
      const delta = e.shiftKey ? -(stepMinutes*2) : -stepMinutes;
      const newVal = addMinutes(lastValid, delta); input.value = newVal; lastValid = newVal; onChange(newVal);
    }
  });
  el.querySelectorAll('.ti24-quick').forEach(btn => btn.addEventListener('click', () => {
    if (disabled) return;
    if (!lastValid) return;
    const delta = Number(btn.dataset.delta);
    const newVal = addMinutes(lastValid, delta); input.value = newVal; lastValid = newVal; onChange(newVal);
  }));
  return el;
}

async function init() {
  state.codes = await api('/api/master/codes');
  bindGlobal();
  switchView(state.view);
  await loadWorkspace();
}

function bindGlobal() {
  $$('.side-nav button').forEach(button=>button.addEventListener('click',()=>switchView(button.dataset.view)));
  $$('.mode-tabs button').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
  $$('.master-tabs:not(.md-tabs) button').forEach(button=>button.addEventListener('click',()=>{state.masterTab=button.dataset.master;state.masterSelectionId=null;state.selectedRecipeId=null; $$('.master-tabs:not(.md-tabs) button').forEach(x=>x.classList.toggle('active',x===button)); loadMaster();}));
  $$('#master-data-tabs button').forEach(button=>button.addEventListener('click',()=>{state.masterDataTab=button.dataset.mdTab;state.masterDataSelectionId=null;$$('#master-data-tabs button').forEach(x=>x.classList.toggle('active',x===button));loadMasterData();}));
  $('#prev-week').addEventListener('click',()=>moveWeek(-1)); $('#next-week').addEventListener('click',()=>moveWeek(1));
  $('#today-week').addEventListener('click',()=>{state.weekStart=mondayOf(new Date());loadWorkspace();});
  $('#week-date-picker').addEventListener('change',e=>{if(e.target.value){state.weekStart=mondayOf(e.target.value);loadWorkspace();}});
  $('#focus-toggle').addEventListener('click',()=>toggleFocus(true)); $('#focus-exit').addEventListener('click',()=>toggleFocus(false));
  $('#document-preview').addEventListener('click',previewCurrentDocument);
  $('#logout-button').addEventListener('click',async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/login';});
  $('#stats-search').addEventListener('click',loadDashboardStats);
  $('#stats-this-week').addEventListener('click',()=>setStatsRange(7));
  $('#stats-four-weeks').addEventListener('click',()=>setStatsRange(28));
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && state.focus) toggleFocus(false);
    if(event.altKey && event.key==='ArrowLeft'){event.preventDefault();moveWeek(-1);}
    if(event.altKey && event.key==='ArrowRight'){event.preventDefault();moveWeek(1);}
  });
}

function switchView(view) {
  state.view=view; $$('.view').forEach(x=>x.classList.toggle('active',x.id===`view-${view}`));
  $$('.side-nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  const titles={workspace:'',master:'메뉴·재료 기준정보','master-data':'기본 데이터 관리',statistics:'통계 보기'};
  $('#page-title').textContent=titles[view]||'';
  $('#top-header').classList.toggle('hidden', view==='workspace');
  if(view==='master') loadMaster(); if(view==='master-data') loadMasterData(); if(view==='statistics') initStatsDashboard();
}

function setMode(mode) {
  state.mode=mode; $$('.mode-tabs button').forEach(x=>x.classList.toggle('active',x.dataset.mode===mode));
  const labels={meal:'식단표 출력',cooking:'조리지시서 출력',preservation:'보존식 기록지 출력',actual:'실제 식수는 별도 저장'};
  $('#document-preview').textContent=labels[mode]; $('#document-preview').disabled=mode==='actual';
  renderWeekBoard(); renderEditor();
}

async function loadWorkspace(keepSelection=true) {
  const start=isoDate(state.weekStart);
  state.workspace=await api(`/api/workspace/weeks?week_start=${start}&weeks=${state.weeks}`);
  const dpe=$('#week-date-picker');if(dpe)dpe.value=isoDate(state.weekStart);
  const wed=$('#week-end-date');if(wed)wed.textContent=state.workspace.end.replace(/-/g,'.');
  $('#focus-week-range').textContent=compactPeriodLabel(state.workspace.start, state.workspace.end);
  const serviceIds=allServiceIds();
  if(!keepSelection || !serviceIds.includes(state.selectedServiceId)){state.selectedServiceId=null;state.selectedService=null;state.selectedMenuItemId=null;}
  renderWeekBoard();
  if(state.selectedServiceId) await selectService(state.selectedServiceId,false); else renderEditor();
}
function allServiceIds(){ return (state.workspace?.weeks||[]).flatMap(w=>w.days.flatMap(d=>d.services.map(s=>s.id))); }
function selectedServiceIdsForDocument(){
  return allServiceIds();
}
function moveWeek(direction){ state.weekStart=addDays(state.weekStart,direction*14); loadWorkspace(false); }
async function toggleFocus(enabled){ state.focus=enabled; state.weeks=2; $('#app-shell').classList.toggle('focus-mode',enabled); $('#focus-toolbar').classList.toggle('hidden',!enabled); $('#focus-toggle').classList.toggle('hidden',enabled); await loadWorkspace(true); if(enabled){const wrap=$('.week-board-wrap');if(wrap)wrap.scrollTop=0;} }

function statusMarkup(service) {
  if(state.mode==='cooking') return `<span class="status-dot ${service.cooking_output?'yes':''}">${service.cooking_output?'✓ 출력':'출력 전'}</span>`;
  if(state.mode==='preservation') return `<span class="status-dot ${service.preservation_completed?'yes':''}">${service.preservation_completed?'✓ 기록':'미기록'}</span>`;
  if(state.mode==='actual') return `<span class="status-dot ${service.actual_recorded?'yes':''}">${service.actual_recorded?`✓ ${numberText(service.actual_count)}명`:'미입력'}</span>`;
  return '';
}
function renderWeekBoard() {
  const board=$('#week-board'); if(!state.workspace){board.innerHTML='';return;}
  board.innerHTML=state.workspace.weeks.map(week=>`<section class="week-section">
    <div class="weekday-grid">${week.days.map(day=>`<article class="day-column ${day.services.some(s=>s.id===state.selectedServiceId)?'selected':''}" data-date="${day.date}">
      <header class="day-head"><div class="day-head-date"><strong>${day.date?day.date.slice(5).replace('-','/'):day.day}</strong><span>${day.weekday}</span></div><button class="add-service-inline" data-add-date="${day.date}">+ 배식</button></header>
      <div class="day-body">${day.services.map(service=>`<div class="service-card ${service.id===state.selectedServiceId?'selected':''}" data-service-id="${service.id}">
        <div class="service-top"><span>${service.meal_type_name}</span><span>${service.service_time?service.service_time.slice(0,5):''}</span></div>
        ${service.concept_title?`<div class="service-concept">${escapeHtml(service.concept_title)}</div>`:''}
        <div class="service-meta">${statusMarkup(service)}</div>
        <div class="menu-lines">${service.menus.map(m=>`<div>${escapeHtml(m.name)}</div>`).join('')||'<span class="muted">메뉴 없음</span>'}</div>
      </div>`).join('')}
      </div>
    </article>`).join('')}</div></section>`).join('');
  $$('.service-card',board).forEach(card=>card.addEventListener('click',()=>selectService(Number(card.dataset.serviceId))));
  $$('[data-add-date]',board).forEach(button=>button.addEventListener('click',()=>openServiceAdd(button.dataset.addDate)));
}

function openServiceAdd(date) {
  const existing=(state.workspace.weeks.flatMap(w=>w.days).find(d=>d.date===date)?.services||[]).map(s=>s.meal_type);
  modal(`<div class="modal-head"><h3>${date} 배식 추가</h3><button class="icon-button" onclick="closeModal()">×</button></div>
  <div class="menu-search-results" id="service-add-list"><p class="muted">불러오는 중…</p></div>`);
  loadServiceAddOptions(date,existing);
}
async function loadServiceAddOptions(date,existing){
  try{
    const defaults=await api('/api/master-data/meal-service-defaults');
    state.mealDefaults=defaults;
    const list=$('#service-add-list');
    list.innerHTML=defaults.map(d=>`<button class="search-menu-card" data-new-service="${d.meal_type}" ${existing.includes(d.meal_type)?'disabled':''}><strong>${escapeHtml(d.display_name)}</strong><span>${existing.includes(d.meal_type)?'이미 작성됨':`기본 ${numberText(d.default_planned_count)}명 · ${d.default_service_time}`}</span></button>`).join('');
    $$('[data-new-service]',list).forEach(button=>button.addEventListener('click',async()=>{try{const service=await api('/api/workspace/services',json('POST',{service_date:date,meal_type:button.dataset.newService}));closeModal();await loadWorkspace(false);await selectService(service.id);}catch(e){toast(e.message,true);}}));
  }catch(e){toast(e.message,true);}
}

async function selectService(id,rerender=true) {
  if(state.selectedServiceId!==id){
    captureCurrentMenuDraft();
  }
  state.selectedServiceId=id; state.selectedService=await api(`/api/workspace/services/${id}`);
  if(!state.selectedMenuItemId || !state.selectedService.menus.some(m=>m.id===state.selectedMenuItemId)) state.selectedMenuItemId=state.selectedService.menus[0]?.id||null;
  initializeMealEditorDraft(state.selectedService);
  if(rerender) renderWeekBoard(); renderEditor();
}

function editorHeader(service,title) {
  return `<div class="editor-title"><div><h3>${service.service_date} · ${service.meal_type_name}</h3><small>${title} · 계획 ${numberText(service.planned_count)}명</small></div><div class="editor-actions"><button class="danger-button" id="delete-service">배식 삭제</button></div></div>`;
}
function renderEditor() {
  const panel=$('#editor-panel'); const service=state.selectedService;
  if(!service){panel.innerHTML='<div class="empty-editor">왼쪽 주간 식단표에서 날짜와 배식을 선택해 주세요.</div>';return;}
  if(state.mode==='meal') renderMealEditor(panel,service);
  else if(state.mode==='cooking') renderCookingEditor(panel,service);
  else if(state.mode==='preservation') renderPreservationEditor(panel,service);
  else renderActualEditor(panel,service);
  const deleteButton=$('#delete-service'); if(deleteButton) deleteButton.addEventListener('click',deleteCurrentService);
}
async function deleteCurrentService(){if(!confirm('이 배식과 메뉴, 기록을 모두 삭제하시겠습니까?'))return;try{await api(`/api/workspace/services/${state.selectedServiceId}`,{method:'DELETE'});state.selectedServiceId=null;state.selectedService=null;await loadWorkspace(false);toast('배식을 삭제했습니다.');}catch(e){toast(e.message,true);}}

function createEditableIngredientGrid(opts) {
  const mode=opts.mode||'service';
  const rows=opts.rows||[];
  const allowPrimary=opts.allowPrimary||false;
  const wrap=document.createElement('div');
  wrap.className='ingredient-grid-wrap';
  const showPrimary=mode==='recipe'&&allowPrimary;
  const headerHtml=showPrimary
    ?'<tr><th class="row-number">#</th><th>재료명</th><th>100인 수량</th><th>단위</th><th>주재료</th><th></th></tr>'
    :'<tr><th class="row-number">#</th><th>재료명</th><th>사용량</th><th>단위</th><th></th></tr>';
  wrap.innerHTML=`<table class="ingredient-grid"><thead>${headerHtml}</thead><tbody class="ig-body"></tbody></table>`;
  const body=$('.ig-body',wrap);
  function rowHtml(item={},index=1){
    const ingId=item.ingredient_id||item.ingredientId||'';
    const name=item.ingredient_name||item.name||'';
    const qty=mode==='recipe'?(item.quantity_per_100??''):(item.quantity_total??'');
    const unit=item.unit||'';
    const primary=showPrimary?(item.is_primary?'checked':''):'';
    return `<tr data-ig-row data-ingredient-id="${ingId}"><td class="row-number">${index}</td><td><input class="ig-name" list="ingredient-options" value="${escapeHtml(name)}"></td><td><input class="ig-qty" type="number" step="0.001" value="${qty}"></td><td><select class="ig-unit"><option value="">단위</option>${state.codes.units.map(u=>`<option ${u===unit?'selected':''}>${u}</option>`).join('')}</select></td>${showPrimary?`<td class="center-cell"><input class="ig-primary" type="checkbox" ${primary}></td>`:''}<td><button class="icon-button ig-remove" aria-label="행 삭제">×</button></td></tr>`;
  }
  function renderRows(){
    body.innerHTML=rows.map((item,i)=>rowHtml(item,i+1)).join('');
    if(rows.length===0)appendRow();
    bindAll();
  }
  function appendRow(values={}){
    const tmp=document.createElement('tbody');
    tmp.innerHTML=rowHtml(values,$$('[data-ig-row]',body).length+1);
    const row=tmp.firstElementChild;
    body.append(row);
    bindRow(row);
    return row;
  }
  function renumber(){$$('[data-ig-row]',body).forEach((row,i)=>$('.row-number',row).textContent=i+1);}
  function bindRow(row){
    $('.ig-remove',row).addEventListener('click',()=>{row.remove();renumber();if(opts.onChange)opts.onChange();});
    const nameInput=$('.ig-name',row);
    nameInput.addEventListener('change',()=>{resolveIngredientRow(row);if(opts.onChange)opts.onChange();});
    nameInput.addEventListener('blur',()=>{resolveIngredientRow(row);});
    if(opts.onChange){
      $('.ig-qty',row).addEventListener('input',opts.onChange);
      $('.ig-unit',row).addEventListener('change',opts.onChange);
      if(showPrimary)$('.ig-primary',row).addEventListener('change',opts.onChange);
    }
  }
  function bindAll(){
    $$('[data-ig-row]',body).forEach(bindRow);
    body.addEventListener('paste',event=>{
      if(!event.target.classList.contains('ig-name'))return;
      const text=event.clipboardData.getData('text');
      if(!text.includes('\n')&&!text.includes('\t'))return;
      event.preventDefault();
      const lines=text.replace(/\r/g,'').split('\n').filter(line=>line.trim()!=='');
      if(lines.length>0&&/^(재료명|수량|사용량|단위|주재료)/i.test(lines[0].split('\t')[0]))lines.shift();
      let row=event.target.closest('tr');
      let index=$$('[data-ig-row]',body).indexOf(row);
      lines.forEach((line,offset)=>{
        const columns=line.split('\t');
        let target=$$('[data-ig-row]',body)[index+offset];
        if(!target)target=appendRow();
        $('.ig-name',target).value=(columns[0]||'').trim();
        const qtyVal=(columns[1]||'').trim();
        $('.ig-qty',target).value=qtyVal;
        if(columns[2]){
          const unit=columns[2].trim();
          if(!state.codes.units.includes(unit)){
            const option=document.createElement('option');
            option.value=unit;option.textContent=unit;
            $('.ig-unit',target).append(option);
          }
          $('.ig-unit',target).value=unit;
        }
        if(showPrimary)$('.ig-primary',target).checked=/^(y|yes|true|1|주재료|o)$/i.test((columns[3]||'').trim());
        resolveIngredientRow(target);
      });
      renumber();
      if(opts.onChange)opts.onChange();
    });
  }
  function resolveIngredientRow(row){
    const nameInput=$('.ig-name',row);
    const unitSelect=$('.ig-unit',row);
    const name=nameInput.value.trim();
    const found=state.ingredientCache.find(i=>i.name===name);
    row.dataset.ingredientId=found?.id||'';
    if(found&&!unitSelect.value)unitSelect.value=found.default_unit||'';
    row.classList.toggle('unresolved-ingredient',Boolean(name)&&!found);
  }
  function collect(){
    return $$('[data-ig-row]',body).map(row=>{
      const name=$('.ig-name',row).value.trim();
      const found=state.ingredientCache.find(i=>i.name===name);
      const result={ingredient_id:found?.id||null,name,quantity_total:$('.ig-qty',row).value===''?null:Number($('.ig-qty',row).value),unit:$('.ig-unit',row).value||null};
      if(showPrimary)result.is_primary=$('.ig-primary',row).checked;
      if(mode==='recipe')result.quantity_per_100=result.quantity_total;
      return result;
    }).filter(row=>row.name);
  }
  renderRows();
  return {element:wrap,appendRow,collect,renumber,resolveIngredientRow};
}

function parseIngredientClipboard(text,mode='service'){
  const lines=text.replace(/\r/g,'').split('\n').filter(line=>line.trim()!=='');
  if(lines.length>0&&/^(재료명|수량|사용량|단위|주재료)/i.test(lines[0].split('\t')[0]))lines.shift();
  return lines.map(line=>{
    const columns=line.split('\t');
    return{ingredientName:(columns[0]||'').trim(),quantity:(columns[1]||'').trim()===''?null:Number(columns[1]),unit:(columns[2]||'').trim()||null};
  });
}

function initializeMealEditorDraft(service){
  state.mealServiceTime=normalizeTime24(service.service_time)||null;
  state.mealEditorDraft={
    serviceId:service.id,
    plannedCount:service.planned_count,
    serviceTime:normalizeTime24(service.service_time),
    conceptTitle:service.concept_title||'',
    serviceNote:service.note||'',
    menus:Object.fromEntries(service.menus.map(menu=>[menu.id,{
      note:menu.note||'',
      isRepresentative:Boolean(menu.is_representative),
      recipeId:menu.recipe_id||null,
      ingredients:structuredClone(menu.ingredients||[]),
      dirty:false
    }]))
  };
  state.mealEditorDirty=false;
}

function captureCurrentMenuDraft(){
  if(!state.mealEditorDraft||!state.selectedMenuItemId)return;
  const menuId=state.selectedMenuItemId;
  const draft=state.mealEditorDraft.menus[menuId];
  if(!draft)return;
  const noteEl=$('#menu-note');
  if(noteEl)draft.note=noteEl.value;
  const repEl=$('#representative');
  if(repEl)draft.is_representative=repEl.checked;
  const gridEl=$('#ingredient-grid-container');
  if(gridEl&&gridEl._gridInstance){
    draft.ingredients=gridEl._gridInstance.collect().map(r=>({ingredient_id:r.ingredient_id,name:r.name,quantity_total:r.quantity_total,unit:r.unit}));
    draft.dirty=true;
  }
}

function getSelectedMenuDraft(){
  if(!state.mealEditorDraft||!state.selectedMenuItemId)return null;
  return state.mealEditorDraft.menus[state.selectedMenuItemId]||null;
}

function markMealEditorDirty(){
  state.mealEditorDirty=true;
  updateMealEditorSaveState();
}

function updateMealEditorSaveState(){
  const el=$('.save-state',$('#editor-panel'));
  if(!el)return;
  if(state.mealEditorDirty){
    el.textContent='저장되지 않은 변경사항이 있습니다.';
  }else{
    el.textContent='저장됨';
  }
}

function switchMealMenu(menuId){
  captureCurrentMenuDraft();
  state.selectedMenuItemId=menuId;
  renderEditor();
}

function checkMealEditorDirty(action){
  if(state.mealEditorDirty){
    return confirm('저장하지 않은 변경사항이 있습니다.\n저장하지 않고 이동하시겠습니까?');
  }
  return true;
}

function renderMealEditor(panel,service) {
  const selected=service.menus.find(m=>m.id===state.selectedMenuItemId)||service.menus[0];
  if(!state.mealEditorDraft||state.mealEditorDraft.serviceId!==service.id){
    initializeMealEditorDraft(service);
  }
  const draft=state.mealEditorDraft;
  panel.innerHTML=editorHeader(service,'식단 작성')+`
  <section class="service-basic-card">
    <div class="service-basic-grid">
      <label class="field">
        <span>식단 제목·컨셉</span>
        <input id="service-concept-title" type="text" maxlength="80" placeholder="예: LA갈비 특식, 명절 특별식" value="${escapeHtml(draft.conceptTitle)}">
      </label>
      <label class="field">
        <span>계획 식수</span>
        <div class="count-input-wrap">
          <input id="planned-count" type="number" min="0" value="${draft.plannedCount}">
        </div>
      </label>
      <label class="field">
        <span>배식시간</span>
        <div id="service-time-cell"></div>
      </label>
    </div>
  </section>
  <div class="panel-section"><div class="panel-section-head"><h4>메뉴 ${service.menus.length}개</h4><button class="secondary-button" id="add-menu">＋ 메뉴 추가</button></div>
    <div class="menu-tabs" role="tablist">${service.menus.map(m=>`<button class="menu-tab ${m.id===selected?.id?'active':''}" data-menu-tab="${m.id}" role="tab" aria-selected="${m.id===selected?.id}">${escapeHtml(m.name)}</button>`).join('')}</div>
    ${selected?menuDetailHtml(selected):'<div class="empty-editor">메뉴를 추가해 주세요.</div>'}
  </div>
  <div class="save-bar"><span class="save-state" aria-live="polite">저장됨</span><button class="primary-button" id="save-service">식단 저장</button></div>`;
  const ti24=createTimeInput24({value:state.mealServiceTime,label:'배식시간',showQuickButtons:false,stepMinutes:5,onChange:v=>{state.mealServiceTime=v;markMealEditorDirty();}});
  $('#service-time-cell').append(ti24);
  $('#planned-count').addEventListener('input',()=>{markMealEditorDirty();});
  $('#service-concept-title').addEventListener('input',()=>{markMealEditorDirty();});
  $('#add-menu').addEventListener('click',openMenuPicker);
  $$('[data-menu-tab]').forEach(button=>button.addEventListener('click',()=>switchMealMenu(Number(button.dataset.menuTab))));
  $('#save-service').addEventListener('click',saveMealEditorTransaction);
  if(selected) bindMenuDetail(selected);
}
function menuDetailHtml(menu) {
  const draft=state.mealEditorDraft?.menus[menu.id];
  const ingredients=draft?.ingredients||menu.ingredients||[];
  return `<div class="menu-row">
    <div class="menu-editor-head">
      <div class="menu-title-area">
        <div class="menu-name-line">
          <strong class="menu-editor-name">${escapeHtml(menu.name)}</strong>
          <label class="representative-toggle">
            <input id="representative" type="checkbox" ${menu.is_representative?'checked':''}>
            <span>대표 메뉴</span>
          </label>
        </div>
        <div class="recipe-summary">${menu.recipe_name?`기본 레시피 v${menu.recipe_version||''}`:'등록 레시피 없음'}</div>
      </div>
      <div class="menu-editor-actions">
        <button type="button" class="ghost-button" id="change-recipe">레시피 변경</button>
        <button type="button" class="icon-button" id="move-up" aria-label="메뉴 위로 이동">↑</button>
        <button type="button" class="icon-button" id="move-down" aria-label="메뉴 아래로 이동">↓</button>
        <button type="button" class="danger-button" id="remove-menu" aria-label="${escapeHtml(menu.name)} 삭제">삭제</button>
      </div>
    </div>
    <label class="field" style="margin-top:8px">메뉴 비고<input id="menu-note" value="${escapeHtml(menu.note||'')}"></label>
    <div class="panel-section-head" style="margin-top:10px"><strong>재료</strong><button class="ghost-button" id="add-ingredient-row">＋ 빈 행</button></div>
    <div id="ingredient-grid-container"></div>
    <div class="grid-status" aria-live="polite"></div>
  </div>`;
}
function bindMenuDetail(menu) {
  $('#remove-menu').addEventListener('click',async()=>{
    if(!confirm(`${menu.name}을 식단에서 삭제할까요?`))return;
    try{
      state.selectedService=await api(`/api/workspace/service-menus/${menu.id}`,{method:'DELETE'});
      state.selectedMenuItemId=state.selectedService.menus[0]?.id||null;
      initializeMealEditorDraft(state.selectedService);
      renderEditor();renderWeekBoard();toast('메뉴를 삭제했습니다.');
    }catch(e){toast(e.message,true);}
  });
  $('#change-recipe').addEventListener('click',()=>openRecipeChange(menu));
  $('#move-up').addEventListener('click',()=>moveSelectedMenu(-1));
  $('#move-down').addEventListener('click',()=>moveSelectedMenu(1));
  $('#representative').addEventListener('change',markMealEditorDirty);
  $('#menu-note').addEventListener('input',markMealEditorDirty);
  const draft=state.mealEditorDraft?.menus[menu.id];
  const ingredients=draft?.ingredients||menu.ingredients||[];
  const grid=createEditableIngredientGrid({
    mode:'service',
    rows:ingredients,
    onChange:()=>{markMealEditorDirty();updateGridStatus();}
  });
  const container=$('#ingredient-grid-container');
  container.innerHTML='';
  container.append(grid.element);
  container._gridInstance=grid;
  $('#add-ingredient-row').addEventListener('click',()=>{grid.appendRow();markMealEditorDirty();});
  updateGridStatus();
}
function updateGridStatus(){
  const gridEl=$('#ingredient-grid-container');
  if(!gridEl||!gridEl._gridInstance)return;
  const rows=gridEl._gridInstance.collect();
  const unresolved=rows.filter(r=>r.name&&!r.ingredient_id);
  const statusEl=$('.grid-status');
  if(statusEl){
    if(unresolved.length>0){
      statusEl.textContent=`미등록 재료 ${unresolved.length}개 — 기준정보에 등록 후 통계에 반영됩니다.`;
      statusEl.className='grid-status grid-status-warn';
    }else if(rows.length>0){
      statusEl.textContent=`재료 ${rows.length}개`;
      statusEl.className='grid-status';
    }else{
      statusEl.textContent='재료를 입력하거나 엑셀에서 붙여넣을 수 있습니다.';
      statusEl.className='grid-status grid-status-hint';
    }
  }
}
async function moveSelectedMenu(delta){const ids=state.selectedService.menus.map(m=>m.id),idx=ids.indexOf(state.selectedMenuItemId),next=idx+delta;if(next<0||next>=ids.length)return;[ids[idx],ids[next]]=[ids[next],ids[idx]];try{state.selectedService=await api(`/api/workspace/services/${state.selectedServiceId}/reorder`,json('POST',{menu_ids:ids}));renderEditor();renderWeekBoard();}catch(e){toast(e.message,true);}}

async function saveMealEditorTransaction() {
  try{
    const saveStateEl=$('.save-state',$('#editor-panel'));
    if(saveStateEl)saveStateEl.textContent='저장 중…';
    captureCurrentMenuDraft();
    const draft=state.mealEditorDraft;
    if(!draft){toast('저장할 데이터가 없습니다.',true);return;}
    const service=state.selectedService;
    const menusBody=service.menus.map(menu=>{
      const md=draft.menus[menu.id]||{};
      return {
        service_menu_id:menu.id,
        note:md.note||null,
        is_representative:md.isRepresentative||false,
        ingredients:(md.ingredients||[]).map(r=>({ingredient_id:r.ingredient_id||null,name:r.name,quantity_total:r.quantity_total,unit:r.unit||null}))
      };
    });
    const body={
      planned_count:Number($('#planned-count').value||0),
      service_time:state.mealServiceTime||null,
      concept_title:$('#service-concept-title')?.value||null,
      note:draft.serviceNote||null,
      menus:menusBody
    };
    state.selectedService=await api(`/api/workspace/services/${state.selectedServiceId}/meal-editor`,json('PUT',body));
    initializeMealEditorDraft(state.selectedService);
    await loadWorkspace(true);
    if(saveStateEl)saveStateEl.textContent='저장됨';
    state.mealEditorDirty=false;
    toast('식단을 저장했습니다.');
  }catch(e){
    const saveStateEl=$('.save-state',$('#editor-panel'));
    if(saveStateEl)saveStateEl.textContent='저장 실패';
    toast(e.message,true);
  }
}

function initializeMenuPickerDraft(){
  const svc=state.selectedService;
  state.menuPickerDraft={
    serviceId: svc?.id||null,
    query:'', role:'ALL',
    results:[], total:0, offset:0,
    selectedItems:[],
    loading:false, submitting:false,
    expandedMenuId:null,
  };
}

function openMenuPicker(){
  captureCurrentMenuDraft();
  initializeMenuPickerDraft();
  renderMenuPickerModal();
  loadMenuPickerResults();
}

function closeMenuPicker(){
  const draft=state.menuPickerDraft;
  if(draft && draft.submitting)return;
  if(draft && draft.selectedItems.length>0){
    if(!confirm('선택한 메뉴가 있습니다. 선택을 취소하고 닫을까요?'))return;
  }
  state.menuPickerDraft=null;
  closeModal();
  const addBtn=$('#add-menu'); if(addBtn)addBtn.focus();
}

function renderMenuPickerModal(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const svc=state.selectedService;
  const dateStr=svc?new Date(svc.service_date).toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}):'';
  const mealName=svc?({BREAKFAST:'조식',LUNCH:'중식',DINNER:'석식',SNACK:'간식'}[svc.meal_type]||svc.meal_type):'';
  const existingCount=svc?svc.menus.length:0;
  const roles=state.codes?.menu_roles||['밥·죽','면·떡','국·탕','찌개·전골','주찬','부찬','김치·절임','샐러드','후식·음료','기타'];

  $('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal menu-picker-modal" role="dialog" aria-modal="true" aria-labelledby="menu-picker-title"><header class="menu-picker-header">
    <div class="menu-picker-header-info">
      <h3 id="menu-picker-title">메뉴 선택</h3>
      <small>${dateStr} ${escapeHtml(mealName)} · 계획 식수 ${numberText(svc?.planned_count)}명 · 식단 ${existingCount}개</small>
    </div>
    <button class="icon-button" id="menu-picker-close" aria-label="닫기">×</button>
  </header>
  <div class="menu-picker-body">
    <aside class="menu-picker-filters">
      <label class="field">메뉴명 검색<input id="picker-search" type="search" placeholder="메뉴명 입력" value="${escapeHtml(draft.query)}"></label>
      <label class="field">메뉴 역할<select id="picker-role"><option value="ALL">전체</option>${roles.map(r=>`<option value="${escapeHtml(r)}" ${r===draft.role?'selected':''}>${escapeHtml(r)}</option>`).join('')}</select></label>
    </aside>
    <main class="menu-picker-results" id="picker-results"></main>
    <aside class="menu-picker-basket" id="picker-basket"></aside>
  </div>
  <footer class="menu-picker-footer">
    <span class="picker-summary" aria-live="polite" id="picker-summary"></span>
    <div class="picker-footer-actions">
      <button class="ghost-button" id="picker-cancel">취소</button>
      <button class="primary-button" id="picker-submit" disabled>가져오기</button>
    </div>
  </footer></section></div>`;
  $('.modal-backdrop').addEventListener('click',e=>{
    if(e.target.classList.contains('modal-backdrop'))closeMenuPicker();
  });

  $('#menu-picker-close').addEventListener('click',closeMenuPicker);
  $('#picker-cancel').addEventListener('click',closeMenuPicker);
  $('#picker-submit').addEventListener('click',submitMenuPickerBatch);
  const searchInput=$('#picker-search');
  searchInput.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();closeMenuPicker();}});
  let debounceTimer;
  searchInput.addEventListener('input',()=>{
    draft.query=searchInput.value;
    clearTimeout(debounceTimer);
    debounceTimer=setTimeout(loadMenuPickerResults,250);
  });
  $('#picker-role').addEventListener('change',e=>{draft.role=e.target.value;loadMenuPickerResults();});
  const resultsEl=$('#picker-results');
  resultsEl.addEventListener('scroll',()=>{
    if(!draft.hasMore||draft.loading)return;
    if(resultsEl.scrollTop+resultsEl.clientHeight>=resultsEl.scrollHeight-80){
      fetchMenuPickerPage();
    }
  });
  document.addEventListener('keydown',pickerEscapeHandler);
  searchInput.focus();
  renderMenuPickerBasket();
  updatePickerSummary();
}

function pickerEscapeHandler(e){
  if(e.key==='Escape'){
    const draft=state.menuPickerDraft;
    if(draft && !draft.submitting){
      e.stopPropagation();
      closeMenuPicker();
    }
  }
}

async function loadMenuPickerResults(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  draft.results=[];
  draft.offset=0;
  draft.total=0;
  draft.hasMore=true;
  draft.loading=false;
  renderMenuPickerResults();
  await fetchMenuPickerPage();
}

async function fetchMenuPickerPage(){
  const draft=state.menuPickerDraft;
  if(!draft||!draft.hasMore||draft.loading)return;
  draft.loading=true;
  if(draft.results.length)renderMenuPickerResults();
  try{
    const params=new URLSearchParams();
    if(draft.query.trim())params.set('q',draft.query.trim());
    if(draft.role&&draft.role!=='ALL')params.set('role',draft.role);
    params.set('active','true');
    if(draft.serviceId)params.set('service_id',draft.serviceId);
    params.set('offset',String(draft.offset));
    params.set('limit','50');
    const data=await api(`/api/master/menus/picker?${params}`);
    const items=data.items||[];
    draft.results=draft.results.concat(items);
    draft.total=data.total||0;
    draft.offset=draft.results.length;
    draft.hasMore=draft.results.length<draft.total;
  }catch(e){toast(e.message,true);draft.hasMore=false;}
  draft.loading=false;
  renderMenuPickerResults();
}

function renderMenuPickerResults(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const el=$('#picker-results');
  if(!el)return;
  if(draft.loading&&!draft.results.length){
    el.innerHTML='<p class="muted" style="padding:20px">불러오는 중…</p>';
    return;
  }
  if(!draft.results.length){
    el.innerHTML='<p class="muted" style="padding:20px">검색 결과가 없습니다.</p>';
    return;
  }
  el.innerHTML=draft.results.map(menu=>{
    const isSelected=draft.selectedItems.some(s=>s.menuId===menu.id);
    const isAdded=menu.already_added;
    const cardClass=`menu-picker-result-card${isSelected?' selected':''}${isAdded?' already-added':''}`;
    const checkboxDisabled=isAdded?'disabled':'';
    const checked=isSelected||isAdded?'checked':'';
    const addedBadge=isAdded?'<span class="picker-added-badge">✓ 이미 식단에 추가됨</span>':'';
    const recipeCount=menu.recipes.length;
    const defaultRecipe=menu.recipes.find(r=>r.id===menu.default_recipe_id);
    const defaultRecipeName=defaultRecipe?`${escapeHtml(defaultRecipe.name)} v${defaultRecipe.version}`:'등록 레시피 없음';
    const expanded=draft.expandedMenuId===menu.id;
    const showRecipes=recipeCount>1||expanded;
    return `<div class="${cardClass}" data-picker-menu="${menu.id}">
      <label class="picker-menu-check">
        <input type="checkbox" data-picker-check="${menu.id}" ${checked} ${checkboxDisabled}>
        <strong>${escapeHtml(menu.name)}</strong>
      </label>
      <div class="picker-menu-meta">${escapeHtml(menu.role)} · 레시피 ${recipeCount}개 · ${escapeHtml(defaultRecipeName)} ${addedBadge}</div>
      ${showRecipes?renderMenuRecipeChoices(menu,isSelected):''}
    </div>`;
  }).join('');

  $$('[data-picker-check]',el).forEach(cb=>{
    if(!cb.disabled)cb.addEventListener('change',()=>toggleMenuPickerItem(Number(cb.dataset.pickerCheck)));
  });
  $$('[data-picker-recipe]',el).forEach(radio=>{
    radio.addEventListener('change',()=>selectMenuPickerRecipe(Number(radio.dataset.pickerMenu),Number(radio.dataset.pickerRecipe)));
  });
  $$('[data-picker-expand]',el).forEach(btn=>{
    btn.addEventListener('click',()=>{
      const mid=Number(btn.dataset.pickerExpand);
      draft.expandedMenuId=draft.expandedMenuId===mid?null:mid;
      renderMenuPickerResults();
    });
  });
  if(draft.hasMore){
    const sentinel=document.createElement('div');
    sentinel.id='picker-scroll-sentinel';
    sentinel.style.cssText='text-align:center;padding:14px;color:#6985a0;font-size:13px';
    sentinel.textContent=draft.loading?'불러오는 중…':'스크롤하여 더 보기';
    el.appendChild(sentinel);
  }
}

function renderMenuRecipeChoices(menu,isSelected){
  const draft=state.menuPickerDraft;
  if(!draft)return'';
  const selectedItem=draft.selectedItems.find(s=>s.menuId===menu.id);
  const selectedRecipeId=selectedItem?.recipeId;
  const selClass=isSelected?' selected':'';
  const chkAttr=isSelected?'checked':'';

  if(menu.recipes.length===0){
    return `<div class="menu-picker-recipe-list${selClass}"><div class="recipe-choices-head">📋 적용 레시피</div><label class="menu-picker-recipe${selClass}"><input type="radio" name="recipe-${menu.id}" data-picker-recipe="0" data-picker-menu="${menu.id}" ${chkAttr}><div><strong>레시피 없이 추가</strong><span>빈 재료 그리드로 추가됩니다.</span></div></label></div>`;
  }
  if(menu.recipes.length===1){
    const r=menu.recipes[0];
    return `<div class="menu-picker-recipe-list${selClass}"><div class="recipe-choices-head">📋 적용 레시피</div><label class="menu-picker-recipe${selClass}"><input type="radio" name="recipe-${menu.id}" data-picker-recipe="${r.id}" data-picker-menu="${menu.id}" ${chkAttr}><div><div class="recipe-title-line"><span class="recipe-ver-badge">v${r.version}</span>${r.is_default?'<span class="recipe-default-badge">기본</span>':''}<strong>${escapeHtml(r.name)}</strong></div><span>재료 ${r.ingredient_count}개 · ${r.ingredient_summary.map(escapeHtml).join(', ')}</span>${r.note?`<small>${escapeHtml(r.note)}</small>`:''}</div></label></div>`;
  }
  const recipesHtml=menu.recipes.map(r=>{
    const isSel=isSelected&&(r.id===selectedRecipeId||(r.id===menu.default_recipe_id&&!selectedRecipeId));
    return `<label class="menu-picker-recipe${isSel?' selected':''}">
      <input type="radio" name="recipe-${menu.id}" value="${r.id}" data-picker-recipe="${r.id}" data-picker-menu="${menu.id}" ${isSel?'checked':''}>
      <div>
        <div class="recipe-title-line">
          <span class="recipe-ver-badge">v${r.version}</span>
          ${r.is_default?'<span class="recipe-default-badge">기본</span>':''}
          <strong>${escapeHtml(r.name)}</strong>
        </div>
        <span>재료 ${r.ingredient_count}개 · ${r.ingredient_summary.map(escapeHtml).join(', ')}${r.ingredient_count>5?` 외 ${r.ingredient_count-5}개`:''}</span>
        ${r.note?`<small>${escapeHtml(r.note)}</small>`:''}
      </div>
    </label>`;
  }).join('');
  return `<div class="menu-picker-recipe-list multi-recipes${selClass}"><div class="recipe-choices-head">📋 적용할 레시피 선택 <small>(${menu.recipes.length}개 레시피 중 선택)</small></div>${recipesHtml}</div>`;
}

function toggleMenuPickerItem(menuId){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const menu=draft.results.find(m=>m.id===menuId);
  if(!menu||menu.already_added)return;
  const idx=draft.selectedItems.findIndex(s=>s.menuId===menuId);
  if(idx>=0){
    draft.selectedItems.splice(idx,1);
  }else{
    const activeRecipes=menu.recipes;
    let recipeId=null,recipeName='레시피 없음',recipeVersion=0;
    if(activeRecipes.length===1){
      recipeId=activeRecipes[0].id;recipeName=activeRecipes[0].name;recipeVersion=activeRecipes[0].version;
    }else if(activeRecipes.length>1){
      const def=activeRecipes.find(r=>r.is_default);
      const picked=def||activeRecipes[activeRecipes.length-1];
      recipeId=picked.id;recipeName=picked.name;recipeVersion=picked.version;
    }
    draft.selectedItems.push({
      menuId, menuName:menu.name, role:menu.role,
      recipeId, recipeName, recipeVersion,
      ingredientCount:activeRecipes.find(r=>r.id===recipeId)?.ingredient_count||0,
    });
  }
  renderMenuPickerResults();
  renderMenuPickerBasket();
  updatePickerSummary();
}

function selectMenuPickerRecipe(menuId,recipeId){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const menu=draft.results.find(m=>m.id===menuId);
  if(!menu||menu.already_added)return;
  let item=draft.selectedItems.find(s=>s.menuId===menuId);
  if(!item){
    let recipeName='레시피 없음',recipeVersion=0,ingredientCount=0;
    if(recipeId!==0){
      const recipe=menu.recipes.find(r=>r.id===recipeId);
      if(recipe){
        recipeName=recipe.name;recipeVersion=recipe.version;ingredientCount=recipe.ingredient_count;
      }
    }
    draft.selectedItems.push({
      menuId, menuName:menu.name, role:menu.role,
      recipeId:recipeId===0?null:recipeId, recipeName, recipeVersion, ingredientCount
    });
  }else{
    if(recipeId===0){
      item.recipeId=null;item.recipeName='레시피 없음';item.recipeVersion=0;item.ingredientCount=0;
    }else{
      const recipe=menu.recipes.find(r=>r.id===recipeId);
      if(recipe){
        item.recipeId=recipeId;item.recipeName=recipe.name;item.recipeVersion=recipe.version;item.ingredientCount=recipe.ingredient_count;
      }
    }
  }
  renderMenuPickerResults();
  renderMenuPickerBasket();
  updatePickerSummary();
}

function renderMenuPickerBasket(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const el=$('#picker-basket');
  if(!el)return;
  if(!draft.selectedItems.length){
    el.innerHTML='<p class="muted" style="padding:14px">선택한 메뉴가 없습니다.<br>왼쪽에서 메뉴를 선택해 주세요.</p>';
    return;
  }
  el.innerHTML=`<h4>선택한 메뉴 ${draft.selectedItems.length}개</h4>`+draft.selectedItems.map((item,idx)=>{
    const recipeText=item.recipeId?`${escapeHtml(item.recipeName)} v${item.recipeVersion}`:'레시피 없음';
    return `<div class="menu-picker-basket-item">
      <div class="basket-item-head"><strong>${idx+1}. ${escapeHtml(item.menuName)}</strong></div>
      <div class="basket-item-recipe">${recipeText}</div>
      <div class="menu-picker-basket-actions">
        <button class="icon-button" data-basket-up="${idx}" aria-label="위로 이동" ${idx===0?'disabled':''}>↑</button>
        <button class="icon-button" data-basket-down="${idx}" aria-label="아래로 이동" ${idx===draft.selectedItems.length-1?'disabled':''}>↓</button>
        <button class="icon-button" data-basket-remove="${idx}" aria-label="제거">×</button>
      </div>
    </div>`;
  }).join('');
  $$('[data-basket-up]',el).forEach(b=>b.addEventListener('click',()=>moveMenuPickerItem(Number(b.dataset.basketUp),-1)));
  $$('[data-basket-down]',el).forEach(b=>b.addEventListener('click',()=>moveMenuPickerItem(Number(b.dataset.basketDown),1)));
  $$('[data-basket-remove]',el).forEach(b=>b.addEventListener('click',()=>removeMenuPickerItem(Number(b.dataset.basketRemove))));
}

function moveMenuPickerItem(idx,direction){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const newIdx=idx+direction;
  if(newIdx<0||newIdx>=draft.selectedItems.length)return;
  [draft.selectedItems[idx],draft.selectedItems[newIdx]]=[draft.selectedItems[newIdx],draft.selectedItems[idx]];
  renderMenuPickerBasket();
  updatePickerSummary();
}

function removeMenuPickerItem(idx){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  draft.selectedItems.splice(idx,1);
  renderMenuPickerResults();
  renderMenuPickerBasket();
  updatePickerSummary();
}

function validateMenuPickerDraft(){
  const draft=state.menuPickerDraft;
  if(!draft)return{valid:false,error:''};
  if(!draft.selectedItems.length)return{valid:false,error:''};
  return{valid:true,error:''};
}

function updatePickerSummary(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const count=draft.selectedItems.length;
  const summary=$('#picker-summary');
  if(summary)summary.textContent=count>0?`선택 ${count}개`:'';
  const submitBtn=$('#picker-submit');
  if(submitBtn){
    submitBtn.disabled=count===0||draft.submitting;
    submitBtn.textContent=count>0?`선택한 메뉴 ${count}개 가져오기`:'가져오기';
  }
}

async function submitMenuPickerBatch(){
  const draft=state.menuPickerDraft;
  if(!draft||!draft.selectedItems.length)return;
  const validation=validateMenuPickerDraft();
  if(!validation.valid)return;
  draft.submitting=true;
  updatePickerSummary();
  const submitBtn=$('#picker-submit');
  if(submitBtn){submitBtn.disabled=true;submitBtn.textContent='가져오는 중…';}
  const cancelBtn=$('#picker-cancel');
  if(cancelBtn)cancelBtn.disabled=true;
  const closeBtn=$('#menu-picker-close');
  if(closeBtn)closeBtn.disabled=true;
  try{
    const items=draft.selectedItems.map((item,idx)=>({
      menu_id:item.menuId,
      recipe_id:item.recipeId,
      sort_order:idx+1,
    }));
    state.selectedService=await api(`/api/workspace/services/${state.selectedServiceId}/menus/batch`,json('POST',{items}));
    const newMenuIds=new Set(draft.selectedItems.map(s=>s.menuId));
    const firstNew=state.selectedService.menus.find(m=>newMenuIds.has(m.menu_id));
    if(firstNew)state.selectedMenuItemId=firstNew.id;
    mergeAddedMenusIntoMealDraft();
    document.removeEventListener('keydown',pickerEscapeHandler);
    state.menuPickerDraft=null;
    closeModal();
    renderEditor();renderWeekBoard();
    toast(`${items.length}개 메뉴를 추가했습니다.`);
  }catch(e){
    draft.submitting=false;
    if(submitBtn){submitBtn.disabled=false;submitBtn.textContent=`선택한 메뉴 ${draft.selectedItems.length}개 가져오기`;}
    if(cancelBtn)cancelBtn.disabled=false;
    if(closeBtn)closeBtn.disabled=false;
    updatePickerSummary();
    toast(e.message,true);
    const summary=$('#picker-summary');
    if(summary)summary.textContent=`오류: ${e.message}`;
  }
}

function mergeAddedMenusIntoMealDraft(){
  const draft=state.mealEditorDraft;
  const svc=state.selectedService;
  if(!draft||!svc)return;
  draft.serviceId=svc.id;
  draft.plannedCount=svc.planned_count;
  draft.conceptTitle=svc.concept_title||'';
  draft.serviceNote=svc.note||'';
  for(const menu of svc.menus){
    if(!draft.menus[menu.id]){
      draft.menus[menu.id]={
        note:menu.note||'',
        isRepresentative:menu.is_representative||false,
        ingredients:(menu.ingredients||[]).map(ing=>({
          ingredient_id:ing.ingredient_id||null,
          name:ing.ingredient_name_snapshot||ing.name||'',
          quantity_total:ing.quantity_total,
          unit:ing.unit||'',
        })),
      };
    }
  }
}

async function openRecipeChange(menuItem){
  try{
    const menu=await api(`/api/master/menus/${menuItem.menu_id}`);
    const recipes=(menu.recipes||[]).filter(recipe=>recipe.active);
    if(!recipes.length){toast('이 메뉴에 등록된 레시피가 없습니다.',true);return;}
    modal(`<div class="modal-head"><h3>${escapeHtml(menu.name)} 레시피 변경</h3><button class="icon-button" onclick="closeModal()">×</button></div><div class="recipe-choice-list">${recipes.map(recipe=>`<label class="recipe-choice"><input type="radio" name="recipe-choice" value="${recipe.id}" ${recipe.id===menuItem.recipe_id?'checked':''}><div><strong>${escapeHtml(recipe.name)}</strong><span>v${recipe.version} · 재료 ${recipe.ingredient_count}개${recipe.is_default?' · 기본':''}</span><small>${recipe.ingredients.map(x=>escapeHtml(x.ingredient_name)).join(', ')}</small></div></label>`).join('')}</div><div class="save-bar"><span>레시피를 바꾸면 현재 재료 목록이 선택 레시피로 교체됩니다.</span><button id="apply-recipe-change" class="primary-button">적용</button></div>`);
    $('#apply-recipe-change').addEventListener('click',async()=>{const picked=$('input[name="recipe-choice"]:checked');if(!picked){toast('레시피를 선택해 주세요.',true);return;}try{state.selectedService=await api(`/api/workspace/service-menus/${menuItem.id}/recipe`,json('PUT',{recipe_id:Number(picked.value)}));closeModal();initializeMealEditorDraft(state.selectedService);renderEditor();renderWeekBoard();toast('레시피를 변경했습니다.');}catch(e){toast(e.message,true);}});
  }catch(e){toast(e.message,true);}
}

function renderCookingEditor(panel,service){panel.innerHTML=editorHeader(service,'조리지시 작성')+`<p class="muted">모든 메뉴에 조리지시를 반드시 작성할 필요는 없습니다. 필요한 메뉴만 입력합니다.</p><div class="panel-section">${service.menus.map(menu=>`<div class="menu-row" data-cooking-row="${menu.id}"><strong>${escapeHtml(menu.name)}</strong><label class="field" style="margin-top:8px">조리지시<textarea class="cook-instruction">${escapeHtml(menu.cooking_instruction||'')}</textarea></label><label class="field">주의·비고<input class="cook-note" value="${escapeHtml(menu.cooking_note||'')}"></label></div>`).join('')||'<div class="empty-editor">식단 작성 모드에서 메뉴를 먼저 추가해 주세요.</div>'}</div><div class="save-bar"><span class="save-state">출력 여부만 주간 카드에 간단히 표시됩니다.</span><button class="primary-button" id="save-cooking">조리지시 저장</button></div>`;$('#save-cooking').addEventListener('click',saveCooking);}
async function saveCooking(){try{for(const row of $$('[data-cooking-row]')){const id=Number(row.dataset.cookingRow),menu=state.selectedService.menus.find(x=>x.id===id);await api(`/api/workspace/service-menus/${id}`,json('PUT',{note:menu.note,is_representative:menu.is_representative,cooking_instruction:$('.cook-instruction',row).value||null,cooking_note:$('.cook-note',row).value||null}));}await selectService(state.selectedServiceId);toast('조리지시를 저장했습니다.');}catch(e){toast(e.message,true);}}

async function renderPreservationEditor(panel,service){panel.innerHTML=editorHeader(service,'보존식 기록')+'<div class="empty-editor">기록을 불러오는 중입니다.</div>';try{const r=await api(`/api/workspace/services/${service.id}/preservation`);state.preservationCollectionTime=normalizeTime24(r.collection_time)||null;panel.innerHTML=editorHeader(service,'보존식 기록')+`<div class="field-grid"><label class="field">채취일시<input id="collected-at" type="datetime-local" value="${dateTimeLocal(r.collected_at)}"></label><label class="field">담당자<input id="manager-name" value="${escapeHtml(r.manager_name||'')}"></label><label class="field">냉동고 온도<input id="freezer-temp" placeholder="예: -18℃" value="${escapeHtml(r.freezer_temperature||'')}"></label><label class="field">폐기일시<input id="disposal-at" type="datetime-local" value="${dateTimeLocal(r.disposal_at)}"></label><label class="field">채취자<input id="collector-name" value="${escapeHtml(r.collector_name||'')}"></label><div class="field"><label>채취시간</label><div id="collection-time-cell"></div></div></div><label class="field">비고<textarea id="preservation-note">${escapeHtml(r.note||'')}</textarea></label><label style="display:block;margin-top:10px"><input id="preservation-completed" type="checkbox" ${r.completed?'checked':''}> 보존식 기록 완료</label><div class="save-bar"><span class="save-state">실제 식수는 별도 모드에서 입력합니다.</span><button class="primary-button" id="save-preservation">보존식 기록 저장</button></div>`;const ti24=createTimeInput24({value:state.preservationCollectionTime,label:'채취시간',onChange:v=>{state.preservationCollectionTime=v;}});$('#collection-time-cell').append(ti24);$('#save-preservation').addEventListener('click',savePreservation);$('#delete-service').addEventListener('click',deleteCurrentService);}catch(e){toast(e.message,true);}}
async function savePreservation(){try{await api(`/api/workspace/services/${state.selectedServiceId}/preservation`,json('PUT',{collected_at:$('#collected-at').value?new Date($('#collected-at').value).toISOString():null,manager_name:$('#manager-name').value||null,freezer_temperature:$('#freezer-temp').value||null,disposal_at:$('#disposal-at').value?new Date($('#disposal-at').value).toISOString():null,collector_name:$('#collector-name').value||null,collection_time:state.preservationCollectionTime||null,note:$('#preservation-note').value||null,completed:$('#preservation-completed').checked}));await selectService(state.selectedServiceId);await loadWorkspace(true);toast('보존식 기록을 저장했습니다.');}catch(e){toast(e.message,true);}}

async function renderActualEditor(panel,service){panel.innerHTML=editorHeader(service,'실제 식수 결과')+'<div class="empty-editor">결과를 불러오는 중입니다.</div>';try{const r=await api(`/api/workspace/services/${service.id}/actual`);panel.innerHTML=editorHeader(service,'실제 식수 결과')+`<div class="result-card"><strong>계획 식수 ${numberText(r.planned_count)}명</strong><p>보존식 기록과 분리된 배식 실적입니다.</p></div><div class="field-grid"><label class="field">실제 식수<input id="actual-count" type="number" min="0" value="${r.actual_count??''}"></label><label class="field">결과 비고<input id="actual-note" value="${escapeHtml(r.note||'')}"></label></div><div class="save-bar"><span class="save-state">${r.recorded_at?`입력일 ${new Date(r.recorded_at).toLocaleString('ko-KR')}`:'아직 입력하지 않았습니다.'}</span><button class="primary-button" id="save-actual">실제 식수 저장</button></div>`;$('#save-actual').addEventListener('click',saveActual);$('#delete-service').addEventListener('click',deleteCurrentService);}catch(e){toast(e.message,true);}}
async function saveActual(){try{await api(`/api/workspace/services/${state.selectedServiceId}/actual`,json('PUT',{actual_count:$('#actual-count').value===''?null:Number($('#actual-count').value),note:$('#actual-note').value||null}));await selectService(state.selectedServiceId);await loadWorkspace(true);toast('실제 식수를 저장했습니다.');}catch(e){toast(e.message,true);}}

function setStatsRange(days){
  const end=new Date();end.setHours(12,0,0,0);
  const start=addDays(end,-(days-1));
  $('#stats-start').value=isoDate(start);$('#stats-end').value=isoDate(end);
  loadDashboardStats();
}
function initStatsDashboard(){
  if(!$('#stats-start').value||!$('#stats-end').value){setStatsRange(28);return;}
  loadDashboardStats();
}
async function loadDashboardStats(){
  const start=$('#stats-start').value,end=$('#stats-end').value;
  if(!start||!end){toast('통계 조회 기간을 입력해 주세요.',true);return;}
  const root=$('#statistics-content');root.innerHTML='<div class="empty-editor">통계를 계산하고 있습니다.</div>';
  try{state.dashboard=await api(`/api/stats/dashboard?start_date=${start}&end_date=${end}`);renderFullStatistics();}catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}
function renderFullStatistics(){
  const root=$('#statistics-content'),data=state.dashboard;if(!root||!data)return;
  const proteinMax=Math.max(1,...data.protein_balance.map(x=>x.services));
  const roleMax=Math.max(1,...data.menu_roles.map(x=>x.count));
  const actualCard=(title,row)=>`<div class="dashboard-kpi"><span>${title}</span><strong>${row.actual_average??'-'}명</strong><small>계획 평균 ${row.planned_average??'-'}명 · 입력 ${row.records}건${row.achievement_rate!==null?` · 계획 대비 ${row.achievement_rate}%`:''}</small></div>`;
  root.innerHTML=`
    <div class="dashboard-kpis">
      <div class="dashboard-kpi"><span>배식</span><strong>${data.service_count}건</strong><small>${data.start_date} ~ ${data.end_date}</small></div>
      <div class="dashboard-kpi"><span>사용 메뉴</span><strong>${data.unique_menu_count}종</strong><small>기간 내 고유 메뉴</small></div>
      ${actualCard('중식 실제 식수',data.actual_meals.lunch)}
      ${actualCard('석식 실제 식수',data.actual_meals.dinner)}
    </div>
    <div class="dashboard-grid">
      <section class="stat-card"><h3>단백질원 구성</h3><p class="muted">해당 재료군이 포함된 배식 횟수입니다.</p><div class="stat-list">${data.protein_balance.map(x=>`<div><div class="stat-line"><span>${x.group}</span><strong>${x.services}회</strong></div><div class="bar"><span style="width:${x.services/proteinMax*100}%"></span></div></div>`).join('')}</div></section>
      <section class="stat-card"><h3>메뉴 역할 구성</h3><p class="muted">밥·국·주찬·부찬 등 식단 역할별 사용 횟수입니다.</p><div class="stat-list">${data.menu_roles.map(x=>`<div><div class="stat-line"><span>${x.role}</span><strong>${x.count}회</strong></div><div class="bar"><span style="width:${x.count/roleMax*100}%"></span></div></div>`).join('')}</div></section>
      <section class="stat-card"><h3>최근 반복 메뉴</h3><p class="muted">현재 조회기간과 직전 4주 사용 이력을 함께 봅니다.</p><div class="stat-list">${data.repeated_menus.map(x=>`<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>기간 ${x.period_count}회 · 이전 ${x.previous_4_weeks}회</strong></div>`).join('')||'<p>반복 메뉴가 없습니다.</p>'}</div></section>
      <section class="stat-card"><h3>재료 분석군</h3><p class="muted">사용 행수와 환산 가능한 예상 중량입니다.</p><div class="stat-list">${data.ingredient_groups.map(x=>`<div class="stat-line"><span>${x.group}</span><strong>${x.usage_rows}건 · ${x.estimated_kg}kg</strong></div>`).join('')}</div></section>
      <section class="stat-card"><h3>자주 사용한 메뉴</h3><div class="stat-list">${data.menu_usage.map(x=>`<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>${x.count}회</strong></div>`).join('')}</div></section>
      <section class="stat-card"><h3>업무 기록 현황</h3><div class="stat-list"><div class="stat-line"><span>조리지시서 출력</span><strong>${data.workflow.cooking_output}건</strong></div><div class="stat-line"><span>보존식 기록 완료</span><strong>${data.workflow.preservation_completed}건</strong></div><div class="stat-line"><span>실제 식수 입력</span><strong>${data.workflow.actual_recorded}건</strong></div></div></section>
    </div>`;
}

function previewCurrentDocument(){
  openDocumentPreviewDialog();
}

function showMigrationPreviewResult(result){
  state.importToken=result.token;const s=result.summary;
  const ok=!result.errors.length;
  $('#migration-result').innerHTML=`<div class="result-card"><h3>${ok?'업로드 가능':'검증 필요'}</h3><p>배식 ${s.meal_types||0}, 메뉴 ${s.menus||0}, 재료 ${s.ingredients||0}, 레시피 ${s.recipe_rows||0}, 식단이력 ${s.meal_history_rows||0}</p>${ok?'':`<pre>${escapeHtml(JSON.stringify(result.errors,null,2))}</pre>`}<div class="inline-form"><select id="import-mode" ${ok?'':'disabled'}><option value="replace">기존 업무데이터 교체</option><option value="merge">기존 데이터에 병합</option></select><button class="primary-button" id="apply-migration" ${ok?'':'disabled'}>기초데이터 생성</button></div></div>`;
  if(ok)$('#apply-migration').addEventListener('click',applyMigration);
}
async function previewMigration(){const file=$('#migration-file').files[0];if(!file){toast('XLSX 파일을 선택해 주세요.',true);return;}const data=new FormData();data.append('file',file);try{$('#migration-result').innerHTML='<div class="result-card">검증 중입니다.</div>';const result=await api('/api/setup/import/preview',{method:'POST',body:data});showMigrationPreviewResult(result);}catch(e){toast(e.message,true);}}
async function applyMigration(){
  if(!confirm('선택한 방식으로 기초데이터와 과거 식단을 생성할까요?'))return;
  const btn=$('#apply-migration');
  try{
    btn.disabled=true;btn.textContent='생성 중…';
    const result=await api('/api/setup/import/apply',json('POST',{token:state.importToken,mode:$('#import-mode').value}));
    $('#migration-result').innerHTML=`<div class="result-card"><h3>생성 완료</h3><pre>${escapeHtml(JSON.stringify(result.result,null,2))}</pre></div>`;
    state.weekStart=mondayOf(new Date());await loadWorkspace(false);toast('기초데이터 생성을 완료했습니다.');
  }catch(e){
    btn.disabled=false;btn.textContent='기초데이터 생성';
    $('#migration-result').innerHTML=`<div class="result-card"><h3 style="color:#9e2f28">생성 실패</h3><pre>${escapeHtml(e.message)}</pre></div>`;
    toast(e.message,true);
  }
}

async function loadMasterData(){
  const root=$('#master-data-content');if(!root)return;
  root.innerHTML='<div class="empty-editor">불러오는 중입니다.</div>';
  try{
    if(state.masterDataTab==='hwpx-templates') await renderHwpxTemplatesView(root);
    else if(state.masterDataTab==='meal-service-defaults') await renderMealServiceDefaultsView(root);
    else renderSetupImportView(root);
  }catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}

function renderSetupImportView(root){
  root.innerHTML=`<div class="narrow-card">
    <h2>기초 데이터 구축</h2>
    <p>XLSX 파일을 선택하고 검증 결과 오류가 없을 때만 서버 업로드 파일로 기초 데이터를 생성합니다.</p>
    <div class="upload-zone">
      <input id="migration-file" type="file" accept=".xlsx">
      <button id="migration-preview" class="secondary-button">선택 파일 검증</button>
    </div>
    <div id="migration-result"></div>
  </div>`;
  $('#migration-preview').addEventListener('click',previewMigration);
}

async function renderHwpxTemplatesView(root){
  const rows=await api('/api/master-data/document-templates');
  const grouped={'MEAL_PLAN':[],'COOKING_INSTRUCTION':[],'PRESERVATION_RECORD':[]};
  rows.forEach(r=>grouped[r.document_type]?.push(r));
  const labels={'MEAL_PLAN':'식단표','COOKING_INSTRUCTION':'조리지시서','PRESERVATION_RECORD':'보존식 기록지'};
  root.innerHTML=`<div class="master-split">
    <section class="master-list-panel">
      ${Object.entries(grouped).map(([type,items])=>`<div class="template-group"><h4>${labels[type]}</h4>${items.length?items.map(r=>`<button class="template-list-item ${r.id===state.masterDataSelectionId?'active':''}" data-template-select="${r.id}" title="${escapeHtml(r.name)}${r.original_filename?` (${escapeHtml(r.original_filename)})`:''}"><strong>${escapeHtml(r.name)}</strong><span>v${r.version}${r.active?' · [활성]':''}${r.is_valid?'':' · 검증실패'}</span></button>`).join(''):'<p class="muted">등록된 양식이 없습니다.</p>'}</div>`).join('')}
    </section>
    <aside id="hwpx-template-editor" class="master-editor-panel"><div class="empty-editor">왼쪽에서 양식을 선택하거나 새 양식을 등록하세요.</div></aside>
  </div>`;
  $$('[data-template-select]',root).forEach(btn=>btn.addEventListener('click',()=>{state.masterDataSelectionId=Number(btn.dataset.templateSelect);$$('[data-template-select]',root).forEach(x=>x.classList.toggle('active',x===btn));renderHwpxTemplatePanel();}));
  renderHwpxTemplatePanel();
}

async function renderHwpxTemplatePanel(){
  const panel=$('#hwpx-template-editor');if(!panel)return;
  const id=state.masterDataSelectionId;
  if(!id){renderHwpxTemplateForm(panel,null);return;}
  try{
    const data=await api(`/api/master-data/document-templates/${id}`);
    renderHwpxTemplateForm(panel,data);
  }catch(e){panel.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}

function renderHwpxTemplateForm(panel,data){
  const id=state.masterDataSelectionId;
  const isNew=!data;
  const d=data||{document_type:'MEAL_PLAN',name:'',description:'',original_filename:''};
  const ph=d.placeholder_summary;
  panel.innerHTML=`<div class="master-editor-head"><div><h3>${isNew?'새 양식 등록':'양식 상세'}</h3><small>HWPX 파일을 업로드하고 검증·활성화합니다.</small></div></div>
  <div class="field-grid"><label class="field">문서 유형<select id="md-doc-type" ${isNew?'':'disabled'}><option value="MEAL_PLAN" ${d.document_type==='MEAL_PLAN'?'selected':''}>식단표</option><option value="COOKING_INSTRUCTION" ${d.document_type==='COOKING_INSTRUCTION'?'selected':''}>조리지시서</option><option value="PRESERVATION_RECORD" ${d.document_type==='PRESERVATION_RECORD'?'selected':''}>보존식 기록지</option></select></label><label class="field">양식명<input id="md-name" value="${escapeHtml(d.name)}"></label></div>
  <label class="field" style="margin-top:8px">설명<input id="md-description" value="${escapeHtml(d.description||'')}"></label>
  <label class="field" style="margin-top:8px">HWPX 파일 업로드<input id="md-file" type="file" accept=".hwpx" ${isNew?'required':''}></label>
  ${ph?`<div class="validation-result"><strong>검증 결과</strong><div class="validation-status ${d.is_valid?'ok':'fail'}">${d.is_valid?'검증 완료':'검증 실패'}</div>${d.validation_message?`<p class="form-error">${escapeHtml(d.validation_message)}</p>`:''}<div class="placeholder-list"><strong>플레이스홀더:</strong> ${(ph.placeholders||[]).map(p=>`<span class="placeholder-chip">${escapeHtml(p)}</span>`).join('')||'<span class="muted">없음</span>'}</div><small>섹션 ${ph.sections||0}개 · 파일 ${ph.files||0}개 · ${numberText(ph.file_size||0)}바이트</small></div>`:''}
  ${data?`<div class="status-badges">${data.active?'<span class="badge badge-active">활성</span>':'<span class="badge badge-inactive">미사용</span>'}${data.is_valid?'<span class="badge badge-ok">검증 완료</span>':'<span class="badge badge-fail">검증 실패</span>'}</div>`:''}
  <div class="save-bar">
    <span class="save-state"></span>
    <div class="button-row">
      ${data?`<button class="ghost-button" id="md-validate">검증</button><button class="ghost-button" id="md-download">다운로드</button>${data.active?'<button class="secondary-button" id="md-deactivate">비활성화</button>':'<button class="primary-button" id="md-activate">활성화</button>'}<button class="danger-button" id="md-delete" ${data.active?'disabled':''}>삭제</button>`:''}
      <button class="primary-button" id="md-save">${isNew?'저장':'양식 수정'}</button>
    </div>
  </div>`;
  $('#md-save').addEventListener('click',async()=>{
    const fileInput=$('#md-file');const file=fileInput.files[0];
    if(isNew&&!file){toast('HWPX 파일을 선택해 주세요.',true);return;}
    const fd=new FormData();fd.append('document_type',$('#md-doc-type').value);fd.append('name',$('#md-name').value);fd.append('description',$('#md-description').value||'');if(file)fd.append('file',file);
    try{$('.save-state').textContent='저장 중…';
      if(isNew){const result=await api('/api/master-data/document-templates',{method:'POST',body:fd});state.masterDataSelectionId=result.id;toast('양식을 등록했습니다.');}
      else{await api(`/api/master-data/document-templates/${id}`,{method:'PUT',body:fd});toast('양식을 수정했습니다.');}
      loadMasterData();
    }catch(e){$('.save-state').textContent='저장 실패';toast(e.message,true);}
  });
  if(data){
    const vBtn=$('#md-validate');if(vBtn)vBtn.addEventListener('click',async()=>{try{await api(`/api/master-data/document-templates/${id}/validate`,{method:'POST'});toast('검증을 완료했습니다.');loadMasterData();}catch(e){toast(e.message,true);}});
    const dlBtn=$('#md-download');if(dlBtn)dlBtn.addEventListener('click',()=>{window.open(`/api/master-data/document-templates/${id}/download`,'_blank');});
    const actBtn=$('#md-activate');if(actBtn)actBtn.addEventListener('click',async()=>{if(!confirm('이 양식을 활성화하시겠습니까? 기존 활성 양식은 비활성화됩니다.'))return;try{await api(`/api/master-data/document-templates/${id}/activate`,{method:'POST'});toast('양식을 활성화했습니다.');loadMasterData();}catch(e){toast(e.message,true);}});
    const deBtn=$('#md-deactivate');if(deBtn)deBtn.addEventListener('click',async()=>{try{await api(`/api/master-data/document-templates/${id}/deactivate`,{method:'POST'});toast('양식을 비활성화했습니다.');loadMasterData();}catch(e){toast(e.message,true);}});
    const delBtn=$('#md-delete');if(delBtn)delBtn.addEventListener('click',async()=>{if(!confirm('이 양식을 삭제하시겠습니까?'))return;try{await api(`/api/master-data/document-templates/${id}`,{method:'DELETE'});state.masterDataSelectionId=null;toast('양식을 삭제했습니다.');loadMasterData();}catch(e){toast(e.message,true);}});
  }
}

async function renderMealServiceDefaultsView(root){
  const rows=await api('/api/master-data/meal-service-defaults');
  const timeValues={};
  rows.forEach(r=>{timeValues[r.meal_type]=r.default_service_time||null;});
  root.innerHTML=`<div class="meal-defaults-wrap">
    <p class="muted" style="margin-bottom:12px">배식 기본값은 신규 식단 작성 시 자동 적용됩니다. 기존 식단에는 소급 적용되지 않습니다.</p>
    <table class="data-table"><thead><tr><th>배식명</th><th>기본 계획식수</th><th>기본 배식시간</th><th>사용 여부</th></tr></thead><tbody>
    ${rows.map(r=>`<tr data-meal-default="${r.meal_type}"><td><strong>${escapeHtml(r.display_name)}</strong></td><td><input class="md-count" type="number" min="0" value="${r.default_planned_count}" data-meal-type="${r.meal_type}"></td><td class="md-time-cell" data-meal-type="${r.meal_type}"></td><td><label><input class="md-active" type="checkbox" ${r.is_active?'checked':''} data-meal-type="${r.meal_type}"> 사용</label></td></tr>`).join('')}
    </tbody></table>
    <div class="save-bar"><span class="save-state"></span><button class="primary-button" id="save-meal-defaults">저장</button></div>
  </div>`;
  $$('[data-meal-default]').forEach(tr=>{
    const mt=tr.dataset.mealDefault;
    const cell=$('.md-time-cell',tr);
    const ti24=createTimeInput24({value:timeValues[mt],label:`${rows.find(r=>r.meal_type===mt)?.display_name||mt} 기본 배식시간`,onChange:v=>{timeValues[mt]=v;}});
    cell.append(ti24);
  });
  $('#save-meal-defaults').addEventListener('click',async()=>{
    const items=$$('[data-meal-default]').map(tr=>({meal_type:tr.dataset.mealDefault,default_planned_count:Number($('.md-count',tr).value||0),default_service_time:timeValues[tr.dataset.mealDefault]||'00:00',is_active:$('.md-active',tr).checked}));
    try{$('.save-state').textContent='저장 중…';await api('/api/master-data/meal-service-defaults',json('PUT',{items}));$('.save-state').textContent='저장됨';toast('배식 기본값을 저장했습니다.');}catch(e){$('.save-state').textContent='저장 실패';toast(e.message,true);}
  });
}

async function loadMaster(){
  const root=$('#master-content');
  root.innerHTML='<div class="empty-editor">불러오는 중입니다.</div>';
  try{
    if(state.masterTab==='menus') await renderMenusMaster(root);
    else await renderIngredientsMaster(root);
  }catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}

async function loadIngredientCache(){
  if(state.ingredientCache.length)return state.ingredientCache;
  state.ingredientCache=await api('/api/master/ingredients?active=true&limit=1000');
  return state.ingredientCache;
}

let _menuRenderToken=0;
async function renderMenusMaster(root,q=''){const token=++_menuRenderToken;
  const rows=await api(`/api/master/menus?q=${encodeURIComponent(q)}&limit=600`);
  if(token!==_menuRenderToken)return;
  const oldInput=$('#master-search');const hadFocus=document.activeElement===oldInput;const curVal=oldInput?.value??q;const curCursor=oldInput?.selectionStart;const curScroll=oldInput?.scrollTop;
  root.innerHTML=`<div class="master-split">
    <section class="master-list-panel">
      <div class="table-tools"><input id="master-search" placeholder="메뉴 검색" value="${escapeHtml(curVal)}"><button class="secondary-button" id="new-menu">＋ 메뉴 등록</button></div>
      <div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>메뉴명</th><th>역할</th><th>레시피</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-menu-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.role)}</td><td>${r.recipe_count}개</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div>
    </section>
    <aside id="master-editor" class="master-editor-panel"></aside>
  </div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  $('#master-search').addEventListener('input',e=>{clearTimeout(window.masterTimer);window.masterTimer=setTimeout(()=>renderMenusMaster(root,e.target.value),250)});
  $('#new-menu').addEventListener('click',()=>{state.masterSelectionId=null;state.selectedRecipeId=null;renderMenuMasterPanel(null);});
  $$('[data-menu-master]').forEach(row=>row.addEventListener('click',()=>{state.masterSelectionId=Number(row.dataset.menuMaster);state.selectedRecipeId=null;$$('[data-menu-master]').forEach(x=>x.classList.toggle('selected-row',x===row));renderMenuMasterPanel(state.masterSelectionId);}));
  if(state.masterSelectionId && rows.some(r=>r.id===state.masterSelectionId)) renderMenuMasterPanel(state.masterSelectionId);
  else renderMenuMasterPanel(null,true);
}

async function renderMenuMasterPanel(id=null,emptyWhenNoSelection=false){
  const panel=$('#master-editor');if(!panel)return;
  if(emptyWhenNoSelection&&id===null){panel.innerHTML='<div class="empty-editor">왼쪽에서 메뉴를 선택하거나 새 메뉴를 등록하세요.</div>';return;}
  let data={id:null,name:'',canonical_name:'',role:'기타',active:true,recipes:[]};
  if(id)data=await api(`/api/master/menus/${id}`);
  const recipes=(data.recipes||[]).sort((a,b)=>a.version-b.version);
  let recipe=null;
  if(id){
    recipe=recipes.find(r=>r.id===state.selectedRecipeId)||recipes.find(r=>r.is_default&&r.active)||recipes.find(r=>r.active)||recipes[0]||null;
    if(state.selectedRecipeId==='new')recipe={id:null,name:`레시피 ${(recipes.at(-1)?.version||0)+1}`,version:(recipes.at(-1)?.version||0)+1,note:'',is_default:recipes.length===0,active:true,ingredients:[]};
    state.selectedRecipeId=recipe?.id??(state.selectedRecipeId==='new'?'new':null);
  }
  await loadIngredientCache();
  panel.innerHTML=`<div class="master-editor-head"><div><h3>${id?'메뉴 수정':'메뉴 등록'}</h3><small>팝업 없이 목록 옆에서 바로 관리합니다.</small></div>${id?'<button class="danger-button" id="archive-menu">삭제</button>':''}</div>
    <div class="field-grid"><label class="field">메뉴명<input id="mm-name" value="${escapeHtml(data.name)}"></label><label class="field">통계 집계명<input id="mm-canonical" value="${escapeHtml(data.canonical_name||data.name)}"></label><label class="field">메뉴 역할<select id="mm-role">${state.codes.menu_roles.map(x=>`<option ${x===data.role?'selected':''}>${x}</option>`).join('')}</select></label><label class="field">사용 여부<select id="mm-active"><option value="true" ${data.active?'selected':''}>사용</option><option value="false" ${!data.active?'selected':''}>미사용</option></select></label></div>
    <div class="panel-action-row"><button class="primary-button" id="save-master-menu">${id?'메뉴 정보 저장':'메뉴 등록'}</button></div>
    ${id?`<div class="recipe-manager">
      <div class="recipe-list-column"><div class="panel-section-head"><div><h4>레시피</h4><small>재료 구성이 다를 때 새 레시피를 만듭니다.</small></div><button class="secondary-button" id="new-recipe">＋ 새 레시피</button></div>
        <div class="recipe-list">${recipes.map(r=>`<button class="recipe-list-item ${recipe?.id===r.id?'active':''}" data-recipe-id="${r.id}"><strong>${escapeHtml(r.name)}</strong><span>v${r.version} · 재료 ${r.ingredient_count}개${r.is_default?' · 기본':''}${r.active?'':' · 미사용'}</span></button>`).join('')||'<p class="muted">등록된 레시피가 없습니다.</p>'}</div>
      </div>
      <div id="recipe-editor" class="recipe-editor-column">${recipe?recipeEditorHtml(recipe):'<div class="empty-editor">새 레시피를 등록해 주세요.</div>'}</div>
    </div>`:'<p class="muted">메뉴를 먼저 등록한 뒤 여러 레시피를 추가할 수 있습니다.</p>'}
    <datalist id="ingredient-options">${state.ingredientCache.map(i=>`<option value="${escapeHtml(i.name)}"></option>`).join('')}</datalist>`;
  $('#save-master-menu').addEventListener('click',async()=>{try{
    const body={name:$('#mm-name').value,canonical_name:$('#mm-canonical').value,role:$('#mm-role').value,active:$('#mm-active').value==='true'};
    const result=id?await api(`/api/master/menus/${id}`,json('PUT',body)):await api('/api/master/menus',json('POST',body));
    state.masterSelectionId=id||result.id;state.selectedRecipeId=null;toast(id?'메뉴 정보를 저장했습니다.':'메뉴를 등록했습니다.');loadMaster();
  }catch(e){toast(e.message,true);}});
  if(id){
    $('#archive-menu').addEventListener('click',async()=>{if(!confirm('메뉴를 삭제(미사용 처리)할까요? 과거 식단 기록은 유지됩니다.'))return;try{await api(`/api/master/menus/${id}`,{method:'DELETE'});state.masterSelectionId=null;state.selectedRecipeId=null;toast('메뉴를 삭제 처리했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
    $('#new-recipe').addEventListener('click',()=>{state.selectedRecipeId='new';renderMenuMasterPanel(id);});
    $$('[data-recipe-id]').forEach(button=>button.addEventListener('click',()=>{state.selectedRecipeId=Number(button.dataset.recipeId);renderMenuMasterPanel(id);}));
    if(recipe)bindRecipeEditor(id,recipe);
  }
}

function recipeEditorHtml(recipe){
  return `<div class="recipe-editor-head"><div><h4>${recipe.id?'레시피 수정':'새 레시피'}</h4><small>수량만 바뀌는 경우 이 레시피를 수정하세요. 재료가 달라질 때만 새 레시피를 만듭니다.</small></div>${recipe.id?'<button class="danger-button" id="archive-recipe">삭제</button>':''}</div>
  <div class="field-grid"><label class="field">레시피명<input id="recipe-name" value="${escapeHtml(recipe.name||'')}"></label><label class="field">상태<select id="recipe-active"><option value="true" ${recipe.active?'selected':''}>사용</option><option value="false" ${!recipe.active?'selected':''}>미사용</option></select></label></div>
  <div class="recipe-options"><label><input id="recipe-default" type="checkbox" ${recipe.is_default?'checked':''}> 식단 추가 시 기본 선택</label></div>
  <div class="grid-help">엑셀에서 <strong>재료명 / 100인 수량 / 단위 / 주재료</strong> 열을 복사한 뒤 첫 번째 재료 칸에 붙여넣을 수 있습니다.</div>
  <div id="recipe-grid-container"></div>
  <div class="panel-action-row"><button class="ghost-button" id="add-recipe-row">＋ 행 추가</button></div>
  <label class="field">레시피 비고<textarea id="recipe-note">${escapeHtml(recipe.note||'')}</textarea></label>
  <div class="save-bar"><span class="save-state">재료 구성은 수량과 무관하게 레시피를 구분합니다.</span><button class="primary-button" id="save-recipe">레시피 저장</button></div>`;
}

function bindRecipeEditor(menuId,recipe){
  const rows=[...(recipe.ingredients||[]),{},{},{}];
  const grid=createEditableIngredientGrid({
    mode:'recipe',
    rows,
    allowPrimary:true
  });
  const container=$('#recipe-grid-container');
  container.innerHTML='';
  container.append(grid.element);
  container._gridInstance=grid;
  $('#add-recipe-row').addEventListener('click',()=>grid.appendRow());
  $('#save-recipe').addEventListener('click',async()=>{try{
    const body={name:$('#recipe-name').value,note:$('#recipe-note').value||null,is_default:$('#recipe-default').checked,active:$('#recipe-active').value==='true',ingredients:grid.collect().map(r=>({ingredient_id:r.ingredient_id,ingredient_name:r.name,quantity_per_100:r.quantity_per_100,unit:r.unit,is_primary:r.is_primary||false}))};
    const result=recipe.id?await api(`/api/master/recipes/${recipe.id}`,json('PUT',body)):await api(`/api/master/menus/${menuId}/recipes`,json('POST',body));
    state.selectedRecipeId=result.id;state.ingredientCache=[];toast('레시피를 저장했습니다.');renderMenuMasterPanel(menuId);
  }catch(e){toast(e.message,true);}});
  const archive=$('#archive-recipe');if(archive)archive.addEventListener('click',async()=>{if(!confirm('이 레시피를 삭제(미사용 처리)할까요? 기존 식단의 재료 스냅샷은 유지됩니다.'))return;try{await api(`/api/master/recipes/${recipe.id}`,{method:'DELETE'});state.selectedRecipeId=null;toast('레시피를 삭제 처리했습니다.');renderMenuMasterPanel(menuId);}catch(e){toast(e.message,true);}});
}

let _ingredientRenderToken=0;
async function renderIngredientsMaster(root,q=''){const token=++_ingredientRenderToken;
  const rows=await api(`/api/master/ingredients?q=${encodeURIComponent(q)}&limit=600`);
  if(token!==_ingredientRenderToken)return;
  const oldInput=$('#master-search');const hadFocus=document.activeElement===oldInput;const curVal=oldInput?.value??q;const curCursor=oldInput?.selectionStart;const curScroll=oldInput?.scrollTop;
  root.innerHTML=`<div class="master-split">
    <section class="master-list-panel"><div class="table-tools"><input id="master-search" placeholder="재료 검색" value="${escapeHtml(curVal)}"><button class="secondary-button" id="new-ingredient">＋ 재료 등록</button></div><div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>재료명</th><th>통계분석군</th><th>단위</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-ingredient-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.stat_group)}</td><td>${escapeHtml(r.default_unit||'')}</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div></section>
    <aside id="master-editor" class="master-editor-panel"></aside></div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  $('#master-search').addEventListener('input',e=>{clearTimeout(window.masterTimer);window.masterTimer=setTimeout(()=>renderIngredientsMaster(root,e.target.value),250)});
  $('#new-ingredient').addEventListener('click',()=>{state.masterSelectionId=null;renderIngredientMasterPanel();});
  $$('[data-ingredient-master]').forEach(row=>row.addEventListener('click',()=>{state.masterSelectionId=Number(row.dataset.ingredientMaster);$$('[data-ingredient-master]').forEach(x=>x.classList.toggle('selected-row',x===row));renderIngredientMasterPanel(state.masterSelectionId);}));
  if(state.masterSelectionId&&rows.some(r=>r.id===state.masterSelectionId))renderIngredientMasterPanel(state.masterSelectionId);else $('#master-editor').innerHTML='<div class="empty-editor">왼쪽에서 재료를 선택하거나 새 재료를 등록하세요.</div>';
}

async function renderIngredientMasterPanel(id=null){
  const panel=$('#master-editor');let data={name:'',stat_group:'기타',default_unit:'',kg_factor:null,analysis_excluded:false,active:true,aliases:[]};if(id)data=await api(`/api/master/ingredients/${id}`);
  panel.innerHTML=`<div class="master-editor-head"><div><h3>${id?'재료 수정':'재료 등록'}</h3><small>식단 통계에 필요한 최소 정보만 관리합니다.</small></div>${id?'<button class="danger-button" id="archive-ingredient">삭제</button>':''}</div><div class="field-grid"><label class="field">표준재료명<input id="im-name" value="${escapeHtml(data.name)}"></label><label class="field">통계분석군<select id="im-group">${state.codes.stat_groups.map(x=>`<option ${x===data.stat_group?'selected':''}>${x}</option>`).join('')}</select></label><label class="field">기본단위<select id="im-unit"><option value="">미지정</option>${state.codes.units.map(x=>`<option ${x===(data.default_unit||'')?'selected':''}>${x}</option>`).join('')}</select></label><label class="field">kg 환산계수(선택)<input id="im-factor" type="number" step="0.0001" value="${data.kg_factor??''}"></label></div><div class="recipe-options"><label><input id="im-excluded" type="checkbox" ${data.analysis_excluded?'checked':''}> 통계 분석 제외</label><label><input id="im-active" type="checkbox" ${data.active?'checked':''}> 사용</label></div>${id&&data.aliases?.length?`<div class="alias-list"><strong>별칭</strong><span>${data.aliases.map(x=>escapeHtml(x.alias)).join(' · ')}</span></div>`:''}<div class="save-bar"><span></span><button class="primary-button" id="save-master-ingredient">저장</button></div>`;
  $('#save-master-ingredient').addEventListener('click',async()=>{try{const body={name:$('#im-name').value,stat_group:$('#im-group').value,default_unit:$('#im-unit').value||null,kg_factor:$('#im-factor').value===''?null:Number($('#im-factor').value),analysis_excluded:$('#im-excluded').checked,active:$('#im-active').checked};const result=id?await api(`/api/master/ingredients/${id}`,json('PUT',body)):await api('/api/master/ingredients',json('POST',body));state.masterSelectionId=id||result.id;state.ingredientCache=[];toast('재료 기준정보를 저장했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
  if(id)$('#archive-ingredient').addEventListener('click',async()=>{if(!confirm('재료를 삭제(미사용 처리)할까요? 과거 식단 기록은 유지됩니다.'))return;try{await api(`/api/master/ingredients/${id}`,{method:'DELETE'});state.masterSelectionId=null;state.ingredientCache=[];toast('재료를 삭제 처리했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
}

document.addEventListener('DOMContentLoaded',()=>init().catch(e=>toast(e.message,true)));
