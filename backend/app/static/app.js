const state = {
  view: 'workspace', mode: 'meal', focus: false, weeks: 2,
  weekStart: mondayOf(new Date()), workspace: null,
  selectedServiceId: null, selectedService: null, selectedMenuItemId: null,
  analysis: null, importToken: null, actualMealUpload: null, weatherUpload: null, weatherOffset: 0, weatherMealOffset: 0, weatherHistoryOffset: 0, masterTab: 'menus', masterSelectionId: null, masterMenuDetailTab: 'recipe',
  masterDataTab: 'hwpx-templates', masterDataSelectionId: null, mealDefaults: null,
  masterIngredientDetailTab: 'info', masterIngredientUsage: {ingredientId:null,items:[],offset:0,total:0,hasMore:false,loading:false,error:''}, masterIngredientUsageQuery:'',
  masterMenuHistory: {menuId:null,items:[],offset:0,total:0,hasMore:false,loading:false,error:'',snapshotCache:{},expandedSnapshotId:null}, masterHistoryFilter:'',
  mealServiceTime: null, preservationCollectionTime: null,
  mealEditorDraft: null, mealEditorDirty: false, mealDetailTab: 'ingredients',
  menuSearchOpen: false, menuSearchQuery: '',
  menuPickerDraft: null,
  codes: null, ingredientCache: [], selectedRecipeId: null,
  documentPreview: null,
  masterMenuQuery: '', masterMenuOffset: 0, masterMenuHasMore: false, masterMenuLoading: false,
  masterIngredientQuery: '', masterIngredientOffset: 0, masterIngredientHasMore: false, masterIngredientLoading: false,
  ordersItems: [], ordersView: 'ingredient', ordersSelection: new Set(), ordersExpanded: new Set(),
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
  const lock = lockUI('HWPX 파일을 만들고 있습니다.');
  try {
    const response = await requestBinary(config.hwpxUrl, json('POST', { start_date: preview.startDate, end_date: preview.endDate }));
    const blob = await response.blob();
    const filename = parseContentDispositionFilename(response.headers.get('content-disposition'), documentPreviewFilename(preview.type, preview.startDate, preview.endDate, 'hwpx'));
    triggerDownload(blob, filename);
    toast('HWPX 파일을 다운로드했습니다.');
  } catch (error) {
    toast(error.message, true);
  } finally {
    lock.release();
  }
}

function toast(message, error=false) {
  const node = document.createElement('div'); node.className=`toast${error?' error':''}`; node.textContent=message;
  $('#toast-root').append(node); setTimeout(()=>node.remove(),3200);
}
function modal(content) {
  $('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal">${content}</section></div>`;
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

// 검색창은 입력할 때마다 조회하지 않고, Enter 키나 조회/검색 버튼을 눌렀을 때만 조회합니다.
// keyup 기준이라 한글 조합 중 Enter를 눌러도 조합이 끝난 글자로 한 번만 조회됩니다.
function bindSearchSubmit(input, button, run){
  if(!input) return;
  input.addEventListener('keydown',e=>{ if(e.key==='Enter') e.preventDefault(); });
  input.addEventListener('keyup',e=>{ if(e.key==='Enter') run(input.value); });
  button?.addEventListener('click',()=>run(input.value));
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
  const mustChange = $('#app-shell')?.dataset.mustChangePassword === 'True' || $('#app-shell')?.dataset.mustChangePassword === 'true';
  if (mustChange) { openChangePasswordModal(true); return; }
  switchView(state.view);
  await loadWorkspace();
}

function bindGlobal() {
  $$('.side-nav button[data-view]').forEach(button=>button.addEventListener('click',()=>switchView(button.dataset.view)));
  $$('.mode-tabs button').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
  $$('.master-tabs:not(.md-tabs) button').forEach(button=>button.addEventListener('click',()=>{state.masterTab=button.dataset.master;state.masterSelectionId=null;state.selectedRecipeId=null;state.masterMenuDetailTab='recipe'; $$('.master-tabs:not(.md-tabs) button').forEach(x=>x.classList.toggle('active',x===button)); loadMaster();}));
  $$('#master-data-tabs button').forEach(button=>button.addEventListener('click',()=>{state.masterDataTab=button.dataset.mdTab;state.masterDataSelectionId=null;$$('#master-data-tabs button').forEach(x=>x.classList.toggle('active',x===button));loadMasterData();}));
  $('#prev-week').addEventListener('click',()=>moveWeek(-1)); $('#next-week').addEventListener('click',()=>moveWeek(1));
  $('#today-week').addEventListener('click',()=>{state.weekStart=mondayOf(new Date());loadWorkspace();});
  $('#week-date-picker').addEventListener('change',e=>{if(e.target.value){state.weekStart=mondayOf(e.target.value);loadWorkspace();}});
  $('#focus-toggle').addEventListener('click',()=>toggleFocus(true)); $('#focus-exit').addEventListener('click',()=>toggleFocus(false));
  $('#document-preview').addEventListener('click',previewCurrentDocument);
  $('#logout-button')?.addEventListener('click',async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/login';});
  $('#change-password-button')?.addEventListener('click',()=>openChangePasswordModal(false));
  $('#create-backup-btn')?.addEventListener('click',createBackup);
  $('#create-archive-btn')?.addEventListener('click',createArchive);
  $('#orders-query-btn')?.addEventListener('click',loadOrders);
  $$('#orders-view-tabs button').forEach(button=>button.addEventListener('click',()=>{state.ordersView=button.dataset.orderView;$$('#orders-view-tabs button').forEach(x=>x.classList.toggle('active',x===button));renderOrders();}));
  $('#orders-status-filter')?.addEventListener('change',renderOrders);
  const ordersSearch=$('#orders-search');
  bindSearchSubmit(ordersSearch,$('#orders-search-btn'),value=>{state.ordersSearchQuery=value;renderOrders();});
  $$('.side-nav-toggle').forEach(btn=>btn.addEventListener('click',toggleNavGroup));
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && state.focus) toggleFocus(false);
    if(event.altKey && event.key==='ArrowLeft'){event.preventDefault();moveWeek(-1);}
    if(event.altKey && event.key==='ArrowRight'){event.preventDefault();moveWeek(1);}
  });
}

function switchView(view) {
  state.view=view; $$('.view').forEach(x=>x.classList.toggle('active',x.id===`view-${view}`));
  $$('.side-nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  const titles={workspace:'',orders:'발주 관리',master:'메뉴·재료 기준정보',analysis:'식수 분석','master-data':'기본 데이터 관리','users':'사용자 관리','backup':'시스템 데이터 백업','archive':'Excel 데이터 아카이브'};
  $('#page-title').textContent=titles[view]||'';
  // 화면 이름만 보여주는 상단 제목 영역은 공간만 차지해서, 이 화면들에서는 숨기고 내용이 바로 위에서 시작하게 합니다.
  $('#top-header').classList.toggle('hidden', ['workspace','orders','master','analysis'].includes(view));
  if(view==='orders') initOrders();
  if(view==='master') loadMaster();
  if(view==='master-data') loadMasterData();
  if(view==='analysis') initAnalysis();
  if(view==='users') initUsers();
  if(view==='backup') initBackup();
  if(view==='archive') initArchive();
  if(['master-data','users','backup','archive'].includes(view)) expandSettingsGroup();
}
function toggleNavGroup(e){
  const group=e.currentTarget.closest('.side-nav-group');
  if(!group)return;
  const collapsed=group.classList.toggle('collapsed');
  e.currentTarget.setAttribute('aria-expanded',String(!collapsed));
}
function expandSettingsGroup(){ const group=$('.side-nav-group[data-group="settings"]'); if(group){ group.classList.remove('collapsed'); $('.side-nav-toggle',group)?.setAttribute('aria-expanded','true'); } }

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
        <div class="service-top"><span>${service.meal_type_name}${service.actual_recorded?` <span class="actual-count-inline">${numberText(service.actual_count)}명</span>`:''}</span><span>${service.service_time?service.service_time.slice(0,5):''}</span></div>
        ${service.concept_title?`<div class="service-concept">${escapeHtml(service.concept_title)}</div>`:''}
        <div class="service-meta">${statusMarkup(service)}${service.note?.trim()?'<span class="service-note-badge">특이사항</span>':''}</div>
        <div class="menu-lines">${service.menus.map(m=>`<div class="${m.is_representative?'representative-menu':''}">${m.is_representative?'<span class="representative-mark" title="메인 메뉴">★</span>':''}${escapeHtml(m.name)}</div>`).join('')||'<span class="muted">메뉴 없음</span>'}</div>
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
  return `<div class="editor-title"><div><h3>${service.service_date} · ${service.meal_type_name}</h3><small>${title?`${title} · `:''}계획 ${numberText(service.planned_count)}명</small></div><div class="editor-actions"><button class="danger-button" id="delete-service">배식 삭제</button></div></div>`;
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
    return `<tr data-ig-row data-ingredient-id="${ingId}" data-ingredient-name="${escapeHtml(name)}"><td class="row-number">${index}</td><td><input class="ig-name" list="ingredient-options" value="${escapeHtml(name)}"></td><td><input class="ig-qty" type="number" step="0.001" value="${qty}"></td><td><select class="ig-unit"><option value="">단위</option>${state.codes.units.map(u=>`<option ${u===unit?'selected':''}>${u}</option>`).join('')}</select></td>${showPrimary?`<td class="center-cell"><input class="ig-primary" type="checkbox" ${primary}></td>`:''}<td><button class="icon-button ig-remove" aria-label="행 삭제">×</button></td></tr>`;
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
    const existingId=row.dataset.ingredientName===name?row.dataset.ingredientId:'';
    const found=state.ingredientCache.find(i=>i.name===name);
    row.dataset.ingredientName=name;
    row.dataset.ingredientId=existingId||found?.id||'';
    if(found&&!unitSelect.value)unitSelect.value=found.default_unit||'';
    row.classList.toggle('unresolved-ingredient',Boolean(name)&&!found);
  }
  function collect(){
    return $$('[data-ig-row]',body).map(row=>{
      const name=$('.ig-name',row).value.trim();
      const snapshotId=row.dataset.ingredientName===name&&row.dataset.ingredientId?Number(row.dataset.ingredientId):null;
      const found=snapshotId?{id:snapshotId}:state.ingredientCache.find(i=>i.name===name);
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
  if(repEl){
    draft.isRepresentative=repEl.checked;
    draft.is_representative=repEl.checked;
  }
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
  state.mealDetailTab='ingredients';
  renderEditor();
}
function switchMealDetailTab(tab){
  captureCurrentMenuDraft();
  state.mealDetailTab=tab;
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
  <div class="editor-scroll">
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
        <label class="field">
          <span>실제 식수</span>
          <div class="actual-count-display">${service.actual_recorded?`${numberText(service.actual_count)}명${service.note?.trim()?' · '+escapeHtml(service.note):''}`:'<span class="muted">미입력</span>'}</div>
        </label>
      </div>
    </section>
    <div class="panel-section meal-menu-section"><div class="panel-section-head"><h4>메뉴 ${service.menus.length}개</h4><button class="secondary-button" id="add-menu">＋ 메뉴 추가</button></div>
      <div class="menu-tabs" role="tablist">${service.menus.map(m=>`<button class="menu-tab ${m.id===selected?.id?'active':''}" data-menu-tab="${m.id}" role="tab" aria-selected="${m.id===selected?.id}">${mainMenuMark(isDraftMainMenu(m))}${escapeHtml(m.name)}</button>`).join('')}</div>
      ${selected?menuDetailHtml(selected):'<div class="empty-editor">메뉴를 추가해 주세요.</div>'}
    </div>
  </div>
  <div class="save-bar"><span class="save-state" aria-live="polite">저장됨</span><button class="primary-button" id="save-service">식단 저장</button></div>`;
  const ti24=createTimeInput24({value:state.mealServiceTime,label:'배식시간',showQuickButtons:false,stepMinutes:5,onChange:v=>{state.mealServiceTime=v;markMealEditorDirty();}});
  $('#service-time-cell').append(ti24);
  $('#planned-count').addEventListener('input',()=>{markMealEditorDirty();if(state.selectedMenuItemId)updateGridStatus(service.menus.find(item=>item.id===state.selectedMenuItemId));});
  $('#service-concept-title').addEventListener('input',()=>{markMealEditorDirty();});
  $('#add-menu').addEventListener('click',openMenuPicker);
  $$('[data-menu-tab]').forEach(button=>button.addEventListener('click',()=>switchMealMenu(Number(button.dataset.menuTab))));
  $('#save-service').addEventListener('click',saveMealEditorTransaction);
  if(selected) bindMenuDetail(selected);
}
function mainMenuMark(isMain){return isMain?'<span class="representative-mark" title="메인 메뉴">★</span>':'';}
function isDraftMainMenu(menu){
  const draftMenu=state.mealEditorDraft?.menus[menu.id];
  return Boolean(draftMenu?draftMenu.isRepresentative:menu.is_representative);
}
// 메인 메뉴(is_representative)는 한 식단(일자×배식)에 최대 하나: 하나를 지정하면 나머지는 해제하고, 해제만 하면 메인 없이 둔다.
function setDraftMainMenu(menuId,isMain){
  const boardService=state.workspace?.weeks.flatMap(week=>week.days).flatMap(day=>day.services).find(service=>service.id===state.selectedServiceId);
  const apply=item=>{item.is_representative=item.id===menuId?isMain:(isMain?false:Boolean(item.is_representative));};
  (state.selectedService?.menus||[]).forEach(apply);
  (boardService?.menus||[]).forEach(apply);
  const draftMenus=state.mealEditorDraft?.menus||{};
  for(const [id,draftMenu] of Object.entries(draftMenus)){
    if(Number(id)===menuId){draftMenu.isRepresentative=isMain;draftMenu.is_representative=isMain;}
    else if(isMain){draftMenu.isRepresentative=false;draftMenu.is_representative=false;}
  }
  $$('[data-menu-tab]').forEach(button=>{
    const item=(state.selectedService?.menus||[]).find(m=>m.id===Number(button.dataset.menuTab));
    if(item)button.innerHTML=`${mainMenuMark(isDraftMainMenu(item))}${escapeHtml(item.name)}`;
  });
}
function menuDetailHtml(menu) {
  const draft=state.mealEditorDraft?.menus[menu.id];
  const ingredients=draft?.ingredients||menu.ingredients||[];
  const detailTab=state.mealDetailTab||'ingredients';
  const representative=draft?.isRepresentative??draft?.is_representative??Boolean(menu.is_representative);
  return `<div class="menu-row">
    <div class="menu-detail-tabs" role="tablist" aria-label="선택 메뉴 편집">
      <button type="button" class="menu-detail-tab ${detailTab==='ingredients'?'active':''}" data-menu-detail-tab="ingredients" role="tab" aria-selected="${detailTab==='ingredients'}">재료 편집</button>
      <button type="button" class="menu-detail-tab ${detailTab==='info'?'active':''}" data-menu-detail-tab="info" role="tab" aria-selected="${detailTab==='info'}">메뉴 정보/비고</button>
    </div>
    <section class="menu-detail-panel ${detailTab==='ingredients'?'active':''}" data-menu-detail-panel="ingredients">
      <div class="panel-section-head ingredient-section-head"><strong>재료 <span class="ingredient-count">${ingredients.filter(item=>item.name||item.ingredient_name).length}개</span></strong><button class="ghost-button" id="add-ingredient-row">＋ 재료 추가</button></div>
      <div id="ingredient-grid-container"></div>
      <div class="grid-status" aria-live="polite"></div>
    </section>
    <section class="menu-detail-panel ${detailTab==='info'?'active':''}" data-menu-detail-panel="info">
      <div class="menu-info-summary">
        <div><span class="menu-info-label">메뉴명</span><strong>${escapeHtml(menu.name)}</strong></div>
        <div><span class="menu-info-label">적용 레시피</span><strong>${menu.recipe_name?escapeHtml(menu.recipe_name):'등록 레시피 없음'}</strong></div>
        <button type="button" class="ghost-button" id="change-recipe">레시피 변경</button>
      </div>
      <div class="menu-info-grid">
        <label class="representative-toggle" title="한 식단에 메인 메뉴는 하나만 지정됩니다. 체크를 해제하면 메인 메뉴 없이 저장할 수 있습니다."><input id="representative" type="checkbox" ${representative?'checked':''}><span>메인 메뉴</span></label>
        <div class="menu-editor-actions">
          <button type="button" class="icon-button" id="move-up" aria-label="메뉴 위로 이동">↑</button>
          <button type="button" class="icon-button" id="move-down" aria-label="메뉴 아래로 이동">↓</button>
          <button type="button" class="danger-button" id="remove-menu" aria-label="${escapeHtml(menu.name)} 삭제">메뉴 삭제</button>
        </div>
      </div>
      <label class="field menu-note-field">메뉴 비고<input id="menu-note" value="${escapeHtml(draft?.note??menu.note??'')}"></label>
    </section>
  </div>`;
}
function bindMenuDetail(menu) {
  $$('[data-menu-detail-tab]').forEach(button=>button.addEventListener('click',()=>switchMealDetailTab(button.dataset.menuDetailTab)));
  $('#change-recipe').addEventListener('click',()=>openRecipeChange(menu));
  $('#remove-menu').addEventListener('click',async()=>{
    if(!confirm(`${menu.name}을 식단에서 삭제할까요?`))return;
    try{
      state.selectedService=await api(`/api/workspace/service-menus/${menu.id}`,{method:'DELETE'});
      state.selectedMenuItemId=state.selectedService.menus[0]?.id||null;
      initializeMealEditorDraft(state.selectedService);
      renderEditor();renderWeekBoard();toast('메뉴를 삭제했습니다.');
    }catch(e){toast(e.message,true);}
  });
  $('#move-up').addEventListener('click',()=>moveSelectedMenu(-1));
  $('#move-down').addEventListener('click',()=>moveSelectedMenu(1));
  $('#representative').addEventListener('change',event=>{
    markMealEditorDirty();
    setDraftMainMenu(menu.id,event.target.checked);
    renderWeekBoard();
  });
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
  updateGridStatus(menu);
}
function updateGridStatus(menu=null){
  const gridEl=$('#ingredient-grid-container');
  if(!gridEl||!gridEl._gridInstance)return;
  const rows=gridEl._gridInstance.collect();
  const unresolved=rows.filter(r=>r.name&&!r.ingredient_id);
  const countEl=$('.ingredient-count');
  if(countEl)countEl.textContent=`${rows.length}개`;
  const statusEl=$('.grid-status');
  if(statusEl){
    if(unresolved.length>0){
      statusEl.textContent=`미등록 재료 ${unresolved.length}개 — 기준정보에 등록해 주세요.`;
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
    detailMenuId:null, detailData:null, detailTab:'recipe',
    historyFilter:'menu', history:[], historyLoading:false, historySelections:[],
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
  const roles=state.codes?.menu_roles||[];

  $('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal menu-picker-modal" role="dialog" aria-modal="true" aria-labelledby="menu-picker-title"><header class="menu-picker-header">
    <div class="menu-picker-header-info"><h3 id="menu-picker-title">메뉴 선택</h3><small>${dateStr} ${escapeHtml(mealName)} · 계획 ${numberText(svc?.planned_count)}명 · 식단 ${existingCount}개</small></div>
    <button class="icon-button" id="menu-picker-close" aria-label="닫기">×</button>
  </header>
  <div class="menu-picker-search"><label class="field">메뉴 검색<span class="search-submit-row"><input id="picker-search" type="search" placeholder="메뉴명 입력 후 Enter 또는 조회" value="${escapeHtml(draft.query)}"><button type="button" class="secondary-button" id="picker-search-btn">조회</button></span></label><label class="field picker-role-filter">메뉴 역할<select id="picker-role"><option value="ALL">전체</option>${roles.map(r=>`<option value="${escapeHtml(r)}" ${r===draft.role?'selected':''}>${escapeHtml(r)}</option>`).join('')}</select></label><span id="picker-result-count" class="picker-result-count"></span></div>
  <div class="menu-picker-body">
    <main class="menu-picker-results" id="picker-results"></main>
    <aside class="menu-picker-detail" id="picker-detail"><div class="picker-detail-empty">메뉴를 선택하면<br>레시피, 재료, 사용 이력을 확인할 수 있습니다.</div></aside>
  </div>
  <footer class="menu-picker-footer"><div class="picker-tray" id="picker-basket"></div><div class="picker-footer-actions"><button class="ghost-button" id="picker-cancel">취소</button><button class="primary-button" id="picker-submit" disabled>가져오기</button></div></footer></section></div>`;
  $('#menu-picker-close').addEventListener('click',closeMenuPicker);
  $('#picker-cancel').addEventListener('click',closeMenuPicker);
  $('#picker-submit').addEventListener('click',submitMenuPickerBatch);
  const searchInput=$('#picker-search');
  searchInput.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();closeMenuPicker();}});
  bindSearchSubmit(searchInput,$('#picker-search-btn'),value=>{draft.query=value;loadMenuPickerResults();});
  $('#picker-role').addEventListener('change',e=>{draft.role=e.target.value;loadMenuPickerResults();});
  const resultsEl=$('#picker-results');
  resultsEl.addEventListener('scroll',()=>{if(!draft.hasMore||draft.loading)return;if(resultsEl.scrollTop+resultsEl.clientHeight>=resultsEl.scrollHeight-80)fetchMenuPickerPage();});
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
  const countEl=$('#picker-result-count');
  if(countEl)countEl.textContent=`검색 결과 ${draft.total||draft.results.length}개`;
  if(draft.loading&&!draft.results.length){el.innerHTML='<p class="muted picker-list-message">불러오는 중…</p>';return;}
  if(!draft.results.length){el.innerHTML='<p class="muted picker-list-message">검색 결과가 없습니다.</p>';return;}
  el.innerHTML=draft.results.map(menu=>{
    const isSelected=draft.selectedItems.some(s=>s.menuId===menu.id);
    const isAdded=menu.already_added;
    const defaultRecipe=menu.recipes.find(r=>r.id===menu.default_recipe_id)||menu.recipes[0];
    const preview=defaultRecipe?.ingredient_summary?.length?`${defaultRecipe.ingredient_summary.map(escapeHtml).join(' · ')}${defaultRecipe.ingredient_count>defaultRecipe.ingredient_summary.length?' · ...':''}`:'등록된 재료 없음';
    return `<div class="picker-menu-row${draft.detailMenuId===menu.id?' detail-active':''}${isSelected?' selected':''}${isAdded?' already-added':''}" data-picker-row="${menu.id}" title="${escapeHtml(preview)}">
      <input type="checkbox" data-picker-check="${menu.id}" ${isSelected||isAdded?'checked':''} ${isAdded?'disabled':''} aria-label="${escapeHtml(menu.name)} 선택">
      <strong class="picker-menu-name">${escapeHtml(menu.name)}</strong>
      <span class="picker-recipe-count">레시피 ${menu.recipes.length}개</span>
      <span class="picker-ingredient-preview">${preview}</span>
      ${isAdded?'<span class="picker-added-badge">이미 추가됨</span>':''}
    </div>`;
  }).join('');
  $$('[data-picker-check]',el).forEach(cb=>{if(!cb.disabled)cb.addEventListener('click',e=>e.stopPropagation());if(!cb.disabled)cb.addEventListener('change',()=>toggleMenuPickerItem(Number(cb.dataset.pickerCheck)));});
  $$('[data-picker-row]',el).forEach(row=>row.addEventListener('click',()=>selectMenuPickerDetail(Number(row.dataset.pickerRow))));
  if(draft.hasMore){const sentinel=document.createElement('div');sentinel.className='picker-scroll-sentinel';sentinel.textContent=draft.loading?'불러오는 중…':'스크롤하여 더 보기';el.appendChild(sentinel);}
  renderPickerDetail();
}

function selectMenuPickerDetail(menuId){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const menu=draft.results.find(item=>item.id===menuId);
  if(!menu)return;
  draft.detailMenuId=menuId;
  draft.detailData=null;
  draft.detailTab='recipe';
  renderMenuPickerResults();
  loadPickerDetail(menuId);
}

async function loadPickerDetail(menuId){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const token=(draft.detailRequestId||0)+1;
  draft.detailRequestId=token;
  try{
    const data=await api(`/api/master/menus/${menuId}`);
    if(state.menuPickerDraft!==draft||draft.detailRequestId!==token)return;
    draft.detailData=data;
    renderPickerDetail();
  }catch(e){toast(e.message,true);}
}

function pickerRecipeForMenu(menu){
  const draft=state.menuPickerDraft;
  const selected=draft?.selectedItems.find(item=>item.menuId===menu.id);
  if(!selected)return null;
  return menu.recipes.find(recipe=>recipe.id===selected.recipeId)||null;
}

function renderPickerDetail(){
  const draft=state.menuPickerDraft;
  const el=$('#picker-detail');
  if(!draft||!el)return;
  const menu=draft.results.find(item=>item.id===draft.detailMenuId);
  if(!menu){el.innerHTML='<div class="picker-detail-empty">메뉴를 선택하면<br>레시피, 재료, 사용 이력을 확인할 수 있습니다.</div>';return;}
  if(!draft.detailData){el.innerHTML=`<div class="picker-detail-heading"><h3>${escapeHtml(menu.name)}</h3></div><p class="muted">메뉴 상세를 불러오는 중…</p>`;return;}
  const detail=draft.detailData;
  el.innerHTML=`<div class="picker-detail-heading"><h3>${escapeHtml(detail.name)}</h3><span>레시피 ${detail.recipe_count}개</span></div>
    <div class="picker-detail-tabs"><button class="picker-detail-tab ${draft.detailTab==='recipe'?'active':''}" data-picker-detail-tab="recipe">레시피/재료</button><button class="picker-detail-tab ${draft.detailTab==='history'?'active':''}" data-picker-detail-tab="history">사용 이력</button></div>
    ${draft.detailTab==='recipe'?renderPickerRecipeDetail(detail,menu):renderPickerHistoryDetail(detail,menu)}`;
  $$('[data-picker-detail-tab]',el).forEach(button=>button.addEventListener('click',()=>{draft.detailTab=button.dataset.pickerDetailTab;renderPickerDetail();if(draft.detailTab==='history')loadPickerHistory(menu.id,menu);}));
  $$('[data-picker-detail-recipe]',el).forEach(radio=>radio.addEventListener('change',()=>{selectMenuPickerRecipe(menu.id,Number(radio.dataset.pickerDetailRecipe));renderPickerDetail();}));
  $$('[data-history-check]',el).forEach(cb=>cb.addEventListener('change',()=>toggleHistorySelection(Number(cb.dataset.historyCheck))));
  $('#history-filter-menu',el)?.addEventListener('click',()=>{draft.historyFilter='menu';loadPickerHistory(menu.id,menu);});
  $('#history-filter-recipe',el)?.addEventListener('click',()=>{draft.historyFilter='recipe';loadPickerHistory(menu.id,menu);});
  $$('[data-history-add-selected]',el).forEach(button=>button.addEventListener('click',addHistorySelections));
}

function recipeLastUsedText(recipe){
  if(!recipe.last_used_date)return '사용 이력 없음';
  const date=recipe.last_used_date.replaceAll('-','.');
  const meal={LUNCH:'중식',DINNER:'석식'}[recipe.last_used_meal_type]||recipe.last_used_meal_type||'';
  return `최근 사용 ${date}${meal?` · ${meal}`:''}`;
}

function recipeTitleText(recipe){
  return String(recipe.name||'레시피').trim();
}

function renderPickerRecipeDetail(detail,menu){
  if(!detail.recipes?.length)return '<p class="picker-detail-empty">등록된 레시피가 없습니다.</p>';
  const selectedRecipe=pickerRecipeForMenu(menu);
  return `<div class="picker-recipe-detail-list">${detail.recipes.filter(recipe=>recipe.active).map(recipe=>{
    const checked=selectedRecipe?.id===recipe.id;
    const ingredients=recipe.ingredients||[];
    return `<label class="picker-recipe-detail ${checked?'selected':''}"><input type="radio" name="picker-detail-recipe" data-picker-detail-recipe="${recipe.id}" ${checked?'checked':''}><div class="picker-recipe-detail-content"><div class="picker-recipe-detail-title"><strong>${escapeHtml(recipeTitleText(recipe))}</strong><span class="picker-recipe-last-used">${escapeHtml(recipeLastUsedText(recipe))}</span></div><div class="picker-ingredient-list">${ingredients.length?ingredients.map(item=>`<span>${escapeHtml(item.ingredient_name)} <b>${item.quantity_per_100??'-'} ${escapeHtml(item.unit||'')}</b></span>`).join(''):'등록된 재료가 없습니다.'}</div></div></label>`;
  }).join('')}</div>`;
}

async function loadPickerHistory(menuId,menu){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  draft.historyLoading=true;
  renderPickerDetail();
  try{
    const selectedRecipe=pickerRecipeForMenu(menu);
    const params=new URLSearchParams({limit:'20'});
    if(draft.historyFilter==='recipe'&&selectedRecipe)params.set('recipe_id',String(selectedRecipe.id));
    draft.history=(await api(`/api/master/menus/${menuId}/usage-history?${params}`)).items||[];
  }catch(e){draft.history=[];toast(e.message,true);}
  draft.historyLoading=false;
  renderPickerDetail();
}

function renderPickerHistoryDetail(detail,menu){
  const draft=state.menuPickerDraft;
  const selectedRecipe=pickerRecipeForMenu(menu);
  if(draft.historyLoading)return '<p class="muted">사용 이력을 불러오는 중…</p>';
  const filterButtons=`<div class="picker-history-filters"><button id="history-filter-menu" class="${draft.historyFilter==='menu'?'active':''}">메뉴 전체</button><button id="history-filter-recipe" class="${draft.historyFilter==='recipe'?'active':''}" ${selectedRecipe?'':'disabled'}>현재 레시피</button></div>`;
  if(!draft.history.length)return `${filterButtons}<p class="picker-detail-empty">이 메뉴의 사용 이력이 없습니다.</p>`;
  return `${filterButtons}<div class="picker-history-list">${draft.history.map(history=>{
    const date=new Date(history.service_date).toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',weekday:'short'});
    const canAdd=Boolean(draft.historySelections?.length);
    return `<article class="picker-history-card"><div class="picker-history-heading"><strong>${date} · ${escapeHtml({LUNCH:'중식',DINNER:'석식'}[history.meal_type]||history.meal_type)}</strong><button class="secondary-button picker-history-add" data-history-add-selected ${canAdd?'':'disabled'}>선택 메뉴 추가</button></div><div class="picker-history-recipe">${escapeHtml(history.recipe_name?recipeTitleText({name:history.recipe_name,version:history.recipe_version}):'레시피 없음')}</div><div class="picker-companion-title">함께 제공된 메뉴</div><div class="picker-companion-list">${history.companions.length?history.companions.map(item=>`<label><input type="checkbox" data-history-check="${item.menu_id}" ${draft.historySelections?.includes(item.menu_id)?'checked':''}><span>${escapeHtml(item.name)}</span></label>`).join(''):'<span class="muted">함께 제공된 메뉴가 없습니다.</span>'}</div></article>`;
  }).join('')}</div>`;
}

function toggleHistorySelection(menuId){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  draft.historySelections=draft.historySelections||[];
  const index=draft.historySelections.indexOf(menuId);
  if(index>=0)draft.historySelections.splice(index,1);else draft.historySelections.push(menuId);
  const detail=$('#picker-detail');
  if(detail)$$('[data-history-add-selected]',detail).forEach(button=>button.disabled=draft.historySelections.length===0);
}

function addHistorySelections(){
  const draft=state.menuPickerDraft;
  if(!draft)return;
  const selectedIds=new Set(draft.historySelections||[]);
  for(const history of draft.history||[]){
    for(const item of history.companions){
      if(!selectedIds.has(item.menu_id))continue;
      addMenuPickerSelection({menuId:item.menu_id,menuName:item.name,role:'기타',recipeId:item.recipe_active?item.recipe_id:null,recipeName:item.recipe_active?(item.recipe_name||'레시피 없음'):'레시피 없음',recipeVersion:item.recipe_active?(item.recipe_version||0):0,ingredientCount:0});
    }
  }
  draft.historySelections=[];
  renderMenuPickerResults();renderMenuPickerBasket();updatePickerSummary();
}

function addMenuPickerSelection(item){
  const draft=state.menuPickerDraft;
  if(!draft||draft.selectedItems.some(selected=>selected.menuId===item.menuId))return;
  if(draft.results.some(menu=>menu.id===item.menuId&&menu.already_added))return;
  draft.selectedItems.push(item);
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
  if(!draft.selectedItems.length){el.innerHTML='<span class="picker-tray-empty">선택 메뉴가 없습니다.</span>';return;}
  el.innerHTML=`<strong class="picker-tray-label">선택 ${draft.selectedItems.length}개</strong><div class="picker-tray-items">${draft.selectedItems.map((item,idx)=>`<div class="picker-tray-item"><span>${idx+1}. ${escapeHtml(item.menuName)}</span><button data-basket-up="${idx}" aria-label="위로 이동" ${idx===0?'disabled':''}>↑</button><button data-basket-down="${idx}" aria-label="아래로 이동" ${idx===draft.selectedItems.length-1?'disabled':''}>↓</button><button data-basket-remove="${idx}" aria-label="제거">×</button></div>`).join('')}</div>`;
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
    modal(`<div class="modal-head"><h3>${escapeHtml(menu.name)} 레시피 변경</h3><button class="icon-button" onclick="closeModal()">×</button></div><div class="recipe-choice-list">${recipes.map(recipe=>`<label class="recipe-choice"><input type="radio" name="recipe-choice" value="${recipe.id}" ${recipe.id===menuItem.recipe_id?'checked':''}><div><strong>${escapeHtml(recipe.name)}</strong><span>재료 ${recipe.ingredient_count}개${recipe.is_default?' · 기본':''}</span><small>${recipe.ingredients.map(x=>escapeHtml(x.ingredient_name)).join(', ')}</small></div></label>`).join('')}</div><div class="save-bar"><span>레시피를 바꾸면 현재 재료 목록이 선택 레시피로 교체됩니다.</span><button id="apply-recipe-change" class="primary-button">적용</button></div>`);
    $('#apply-recipe-change').addEventListener('click',async()=>{const picked=$('input[name="recipe-choice"]:checked');if(!picked){toast('레시피를 선택해 주세요.',true);return;}try{state.selectedService=await api(`/api/workspace/service-menus/${menuItem.id}/recipe`,json('PUT',{recipe_id:Number(picked.value)}));closeModal();initializeMealEditorDraft(state.selectedService);renderEditor();renderWeekBoard();toast('레시피를 변경했습니다.');}catch(e){toast(e.message,true);}});
  }catch(e){toast(e.message,true);}
}

function renderCookingEditor(panel,service){const notedMenus=service.menus.filter(menu=>(menu.note||'').trim());const noteRows=service.menus.map(menu=>`<div class="cooking-menu-note-row ${(menu.note||'').trim()?'':'no-note'}"><strong>${escapeHtml(menu.name)}</strong><span>${(menu.note||'').trim()?escapeHtml(menu.note):'비고 없음'}</span></div>`).join('');panel.innerHTML=editorHeader(service,'')+`<p class="cooking-help">식단 작성에서 입력한 메뉴 비고가 조리지시서에 자동 반영됩니다. 배식 후 특이사항이 있을 경우 아래에 기록하세요.</p><section class="panel-section cooking-source-section"><div class="panel-section-head"><h4>식단 작성 비고</h4>${service.menus.length?'<button type="button" class="secondary-button" id="show-all-cooking-notes">전체 메뉴 보기</button>':''}</div><div id="cooking-menu-notes" class="cooking-menu-notes">${noteRows}</div><p id="cooking-notes-empty" class="muted" ${notedMenus.length?'hidden':''}>식단 작성에서 입력된 메뉴 비고가 없습니다.</p></section><section class="panel-section cooking-post-section"><div class="panel-section-head"><h4>배식 후 특이사항</h4></div><textarea id="post-service-note" class="post-service-note" placeholder="배식 후 확인된 특이사항을 입력하세요. 예: 밥 부족, 잔반 많음, 메뉴 반응, 민원 등">${escapeHtml(service.note||'')}</textarea></section><div class="save-bar"><span class="save-state">특이사항이 없어도 정상입니다.</span><button class="primary-button" id="save-cooking">특이사항 저장</button></div>`;$('#show-all-cooking-notes')?.addEventListener('click',()=>{const notes=$('#cooking-menu-notes');const showAll=!notes.classList.contains('show-all');notes.classList.toggle('show-all',showAll);$('#cooking-notes-empty')?.toggleAttribute('hidden',showAll||notedMenus.length>0);$('#show-all-cooking-notes').textContent=showAll?'비고 있는 메뉴만':'전체 메뉴 보기';});$('#save-cooking').addEventListener('click',saveCooking);}
async function saveCooking(){try{await api(`/api/workspace/services/${state.selectedServiceId}/post-service-note`,json('PUT',{note:$('#post-service-note').value||null}));await selectService(state.selectedServiceId);await loadWorkspace(true);toast('특이사항을 저장했습니다.');}catch(e){toast(e.message,true);}}

async function renderPreservationEditor(panel,service){panel.innerHTML=editorHeader(service,'보존식 기록')+'<div class="empty-editor">기록을 불러오는 중입니다.</div>';try{const r=await api(`/api/workspace/services/${service.id}/preservation`);state.preservationCollectionTime=normalizeTime24(r.collection_time)||null;panel.innerHTML=editorHeader(service,'보존식 기록')+`<div class="field-grid"><label class="field">채취일시<input id="collected-at" type="datetime-local" value="${dateTimeLocal(r.collected_at)}"></label><label class="field">담당자<input id="manager-name" value="${escapeHtml(r.manager_name||'')}"></label><label class="field">냉동고 온도<input id="freezer-temp" placeholder="예: -18℃" value="${escapeHtml(r.freezer_temperature||'')}"></label><label class="field">폐기일시<input id="disposal-at" type="datetime-local" value="${dateTimeLocal(r.disposal_at)}"></label><label class="field">채취자<input id="collector-name" value="${escapeHtml(r.collector_name||'')}"></label><div class="field"><label>채취시간</label><div id="collection-time-cell"></div></div></div><label class="field">비고<textarea id="preservation-note">${escapeHtml(r.note||'')}</textarea></label><label style="display:block;margin-top:10px"><input id="preservation-completed" type="checkbox" ${r.completed?'checked':''}> 보존식 기록 완료</label><div class="save-bar"><span class="save-state">실제 식수는 별도 모드에서 입력합니다.</span><button class="primary-button" id="save-preservation">보존식 기록 저장</button></div>`;const ti24=createTimeInput24({value:state.preservationCollectionTime,label:'채취시간',onChange:v=>{state.preservationCollectionTime=v;}});$('#collection-time-cell').append(ti24);$('#save-preservation').addEventListener('click',savePreservation);$('#delete-service').addEventListener('click',deleteCurrentService);}catch(e){toast(e.message,true);}}
async function savePreservation(){try{await api(`/api/workspace/services/${state.selectedServiceId}/preservation`,json('PUT',{collected_at:$('#collected-at').value?new Date($('#collected-at').value).toISOString():null,manager_name:$('#manager-name').value||null,freezer_temperature:$('#freezer-temp').value||null,disposal_at:$('#disposal-at').value?new Date($('#disposal-at').value).toISOString():null,collector_name:$('#collector-name').value||null,collection_time:state.preservationCollectionTime||null,note:$('#preservation-note').value||null,completed:$('#preservation-completed').checked}));await selectService(state.selectedServiceId);await loadWorkspace(true);toast('보존식 기록을 저장했습니다.');}catch(e){toast(e.message,true);}}

async function renderActualEditor(panel,service){panel.innerHTML=editorHeader(service,'실제 식수 결과')+'<div class="empty-editor">결과를 불러오는 중입니다.</div>';try{const r=await api(`/api/workspace/services/${service.id}/actual`);panel.innerHTML=editorHeader(service,'실제 식수 결과')+`<div class="result-card"><strong>계획 식수 ${numberText(r.planned_count)}명</strong><p>보존식 기록과 분리된 배식 실적입니다.</p></div><div class="field-grid"><label class="field">실제 식수<input id="actual-count" type="number" min="0" value="${r.actual_count??''}"></label><label class="field">특이 사항<input id="actual-note" value="${escapeHtml(r.note||'')}"></label></div><div class="save-bar"><span class="save-state">${r.recorded_at?`입력일 ${new Date(r.recorded_at).toLocaleString('ko-KR')}`:'아직 입력하지 않았습니다.'}</span><button class="primary-button" id="save-actual">실제 식수 저장</button></div>`;$('#save-actual').addEventListener('click',saveActual);$('#delete-service').addEventListener('click',deleteCurrentService);}catch(e){toast(e.message,true);}}
async function saveActual(){try{await api(`/api/workspace/services/${state.selectedServiceId}/actual`,json('PUT',{actual_count:$('#actual-count').value===''?null:Number($('#actual-count').value),note:$('#actual-note').value||null}));await selectService(state.selectedServiceId);await loadWorkspace(true);toast('실제 식수를 저장했습니다.');}catch(e){toast(e.message,true);}}

function previewCurrentDocument(){
  openDocumentPreviewDialog();
}

function showMigrationPreviewResult(result){
  state.importToken=result.token;const s=result.summary;
  const ok=!result.errors.length;
  $('#migration-result').innerHTML=`<div class="result-card"><h3>${ok?'업로드 가능':'검증 필요'}</h3><p>배식 ${s.meal_types||0}, 메뉴 ${s.menus||0}, 재료 ${s.ingredients||0}, 레시피 ${s.recipe_rows||0}, 식단이력 ${s.meal_history_rows||0}</p>${ok?'':`<pre>${escapeHtml(JSON.stringify(result.errors,null,2))}</pre>`}<div class="inline-form"><select id="import-mode" ${ok?'':'disabled'}><option value="replace">기존 업무데이터 교체</option><option value="merge">기존 데이터에 병합</option></select><button class="primary-button" id="apply-migration" ${ok?'':'disabled'}>기초데이터 생성</button></div></div>`;
  if(ok)$('#apply-migration').addEventListener('click',applyMigration);
}
async function previewMigration(){const file=$('#migration-file').files[0];if(!file){toast('XLSX 파일을 선택해 주세요.',true);return;}const data=new FormData();data.append('file',file);const lock=lockUI('기초데이터 파일을 올리고 검증하고 있습니다.');try{$('#migration-result').innerHTML='<div class="result-card">검증 중입니다.</div>';const result=await api('/api/setup/import/preview',{method:'POST',body:data});showMigrationPreviewResult(result);}catch(e){$('#migration-result').innerHTML='';toast(e.message,true);}finally{lock.release();}}
async function waitForMigrationImport(token, lock=null){
  let connectionErrors=0;
  while(true){
    await new Promise(resolve=>setTimeout(resolve,2000));
    let job;
    try{job=await api(`/api/setup/import/jobs/${encodeURIComponent(token)}`);connectionErrors=0;}
    catch(e){
      connectionErrors++;
      if(lock) lock.update(`서버 응답을 기다리고 있습니다 (${connectionErrors}회). 작업은 서버에서 계속됩니다.`, null);
      $('#migration-result').innerHTML=`<div class="result-card"><h3>기초데이터 생성 중</h3><p>서버 작업은 계속 진행 중이며 진행 상태를 다시 확인하고 있습니다 (${connectionErrors}회).</p></div>`;
      continue;
    }
    if(job.status==='PROCESSING'){
      if(lock) lock.update(job.progress?.message?`기초데이터 생성 중 · ${job.progress.message}`:'기초데이터를 생성하고 있습니다.', typeof job.progress?.percent==='number'?job.progress.percent:null);
      $('#migration-result').innerHTML='<div class="result-card"><h3>기초데이터 생성 중</h3><p>대량 데이터를 반영하고 있습니다. 이 화면을 닫지 않아도 서버에서 작업은 계속됩니다.</p></div>';
      continue;
    }
    if(job.status==='COMPLETED')return job.result||{};
    const message=(job.errors||[]).map(item=>item.message).filter(Boolean).join('\\n')||`처리 상태: ${job.status}`;
    throw new Error(message);
  }
}
async function applyMigration(){
  if(!confirm('선택한 방식으로 기초데이터와 과거 식단을 생성할까요?'))return;
  const btn=$('#apply-migration');
  const lock=lockUI('기초데이터 생성을 시작하고 있습니다.', 0);
  try{
    btn.disabled=true;btn.textContent='생성 중…';
    await api('/api/setup/import/apply',json('POST',{token:state.importToken,mode:$('#import-mode').value}));
    $('#migration-result').innerHTML='<div class="result-card"><h3>기초데이터 생성 중</h3><p>서버에서 반영 작업을 시작했습니다.</p></div>';
    const result=await waitForMigrationImport(state.importToken, lock);
    lock.update('화면을 새로 고치고 있습니다.', 100);
    $('#migration-result').innerHTML=`<div class="result-card"><h3>생성 완료</h3><pre>${escapeHtml(JSON.stringify(result,null,2))}</pre></div>`;
    state.weekStart=mondayOf(new Date());await loadWorkspace(false);toast('기초데이터 생성을 완료했습니다.');
  }catch(e){
    btn.disabled=false;btn.textContent='기초데이터 생성';
    $('#migration-result').innerHTML=`<div class="result-card"><h3 style="color:#9e2f28">생성 실패</h3><pre>${escapeHtml(e.message)}</pre></div>`;
    toast(e.message,true);
  }finally{lock.release();}
}

async function loadMasterData(){
  const root=$('#master-data-content');if(!root)return;
  root.innerHTML='<div class="empty-editor">불러오는 중입니다.</div>';
  try{
    if(state.masterDataTab==='hwpx-templates') await renderHwpxTemplatesView(root);
    else if(state.masterDataTab==='meal-service-defaults') await renderMealServiceDefaultsView(root);
    else if(state.masterDataTab==='actual-meal-upload') renderActualMealUploadView(root);
    else if(state.masterDataTab==='weather') await renderWeatherView(root);
    else renderSetupImportView(root);
  }catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}

async function renderWeatherView(root){
  root.innerHTML=`<div class="weather-management">
    <section class="narrow-card"><h2>날씨정보 관리</h2><p>일별 자료와 시간별 관측자료를 저장합니다. 시간별 자료의 11·12시는 중식, 17·18시는 석식 시간대 날씨로 함께 저장되고, 하루 20시간 이상 있는 날은 일별 자료(평균·최저·최고기온, 강수 합계, 평균습도)도 자동으로 만듭니다.</p>
      <details class="weather-format-help"><summary>지원하는 파일 형식</summary><ul>
        <li><strong>weather.nuni.co.kr 시간별 내려받기 CSV</strong> (권장): 첫 줄 <code># source=KMA …</code> 안내행, 열 <code>observation_datetime, station_id, station_name, temperature, precipitation, humidity, wind_speed, source_kind</code>. 파일을 그대로 올리면 됩니다.</li>
        <li>같은 시각이 <code>01:00</code>과 <code>01:00:00</code>처럼 두 번 들어 있고 값이 같으면 한 건만 저장합니다. 값이 다르면 오류로 표시합니다.</li>
        <li>시간별 자료에서 강수량 칸이 비어 있으면 비가 오지 않은 것(0mm)으로 저장합니다(기상청 표기 방식).</li>
        <li>기상청 일별 자료(일시·지점·평균기온·최저기온·최고기온·일강수량·평균상대습도·적설·일조) XLSX/XLS/CSV도 그대로 지원합니다. 기상청 일별 파일로 올린 날은 시간별 집계가 덮어쓰지 않습니다.</li>
        <li>인코딩: UTF-8(BOM 포함), CP949/EUC-KR 자동 인식 · 최대 20MB, 10만 행.</li>
        <li>같은 파일을 다시 올려도 날짜·시각·지점 기준으로 덮어쓰므로 중복 저장되지 않습니다. ‘파일 분석’만으로는 저장되지 않고 ‘DB 반영’을 눌러야 저장됩니다.</li>
      </ul></details>
      <div class="upload-zone"><input id="weather-file" type="file" accept=".xlsx,.xls,.csv"><button class="secondary-button" id="weather-preview">파일 분석</button><button class="ghost-button" id="weather-reset">초기화</button></div><div id="weather-preview-result"></div>
    </section>
    <section class="panel-section"><div class="panel-section-head"><h3>배식 시간대 날씨</h3></div><div class="table-tools weather-filters"><input id="weather-start" type="date" title="시작일"><input id="weather-end" type="date" title="종료일"><input id="weather-station" placeholder="관측지점 검색"><input id="weather-min-temp" type="number" step="0.1" placeholder="평균기온 최소"><input id="weather-max-temp" type="number" step="0.1" placeholder="평균기온 최대"><select id="weather-rain"><option value="all">강수 전체</option><option value="yes">강수 있음</option><option value="no">강수 0mm</option></select><button class="secondary-button" id="weather-search">조회</button></div><div id="weather-meal-records"><div class="empty-editor">불러오는 중입니다.</div></div></section>
    <section class="panel-section"><div class="panel-section-head"><h3>저장된 일별 날씨자료</h3></div><div id="weather-records"><div class="empty-editor">불러오는 중입니다.</div></div></section>
    <section class="panel-section"><div class="panel-section-head"><h3>업로드 이력</h3></div><div id="weather-uploads"><div class="empty-editor">불러오는 중입니다.</div></div></section>
  </div>`;
  $('#weather-preview').addEventListener('click',previewWeatherFile);$('#weather-reset').addEventListener('click',()=>{state.weatherUpload=null;$('#weather-file').value='';$('#weather-preview-result').innerHTML='';});$('#weather-search').addEventListener('click',()=>{state.weatherOffset=0;state.weatherMealOffset=0;loadWeatherRecords();loadMealPeriodWeatherRecords();});
  await Promise.all([loadWeatherRecords(),loadMealPeriodWeatherRecords(),loadWeatherUploads()]);
}

function weatherNumber(value,suffix=''){return value===null||value===undefined?'—':`${numberText(value)}${suffix}`;}
function renderWeatherPreview(response){
  state.weatherUpload=response;const s=response.summary;const root=$('#weather-preview-result');const hourly=s.data_granularity==='hourly';const labels={observation_date:'관측일자',observation_datetime:'관측일시',station_id:'지점번호',station_name:'지점명',avg_temp:'평균기온',temperature:'기온',min_temp:'최저기온',max_temp:'최고기온',precipitation:'강수량',avg_humidity:'평균습도',humidity:'습도',snow_depth:'적설',sunshine_hours:'일조시간',wind_speed:'풍속',source_kind:'자료구분'};
  const table=hourly?`<div class="table-wrap"><table class="data-table"><thead><tr><th>행</th><th>관측일시</th><th>지점</th><th>기온</th><th>강수</th><th>습도</th><th>풍속</th><th>적용 배식</th><th>상태</th><th>확인사항</th></tr></thead><tbody>${response.preview_rows.map(row=>{const hour=Number((row.observation_datetime||'').slice(11,13));const meal=[11,12].includes(hour)?'중식':[17,18].includes(hour)?'석식':'배식시간 외';return `<tr><td>${row.source_row}</td><td>${escapeHtml(row.observation_datetime||'—')}</td><td>${escapeHtml(row.station_name||row.station_id||'—')}<small class="muted"> ${escapeHtml(row.station_id||'')}</small></td><td>${weatherNumber(row.temperature,'℃')}</td><td>${weatherNumber(row.precipitation,'mm')}</td><td>${weatherNumber(row.humidity,'%')}</td><td>${weatherNumber(row.wind_speed,'m/s')}</td><td>${meal}</td><td><span class="badge ${row.status==='오류'?'badge-fail':row.status==='수정'?'badge-warn':row.status==='신규'?'badge-ok':'badge-inactive'}">${row.status}</span></td><td class="${row.error?'form-error':'muted'}">${escapeHtml(row.error||row.warnings.join(' · '))}</td></tr>`;}).join('')}</tbody></table></div>`:`<div class="table-wrap"><table class="data-table"><thead><tr><th>행</th><th>날짜</th><th>지점</th><th>평균</th><th>최저</th><th>최고</th><th>강수</th><th>습도</th><th>상태</th><th>확인사항</th></tr></thead><tbody>${response.preview_rows.map(row=>`<tr><td>${row.source_row}</td><td>${row.observation_date||'—'}</td><td>${escapeHtml(row.station_name||row.station_id||'—')}<small class="muted"> ${escapeHtml(row.station_id||'')}</small></td><td>${weatherNumber(row.avg_temp,'℃')}</td><td>${weatherNumber(row.min_temp,'℃')}</td><td>${weatherNumber(row.max_temp,'℃')}</td><td>${weatherNumber(row.precipitation,'mm')}</td><td>${weatherNumber(row.avg_humidity,'%')}</td><td><span class="badge ${row.status==='오류'?'badge-fail':row.status==='수정'?'badge-warn':row.status==='신규'?'badge-ok':'badge-inactive'}">${row.status}</span></td><td class="${row.error?'form-error':'muted'}">${escapeHtml(row.error||row.warnings.join(' · '))}</td></tr>`).join('')}</tbody></table></div>`;
  root.innerHTML=`<div class="result-card"><h3>파일 분석 결과</h3><div class="stats-mini"><div class="stat-mini-card"><strong>파일</strong><span>${escapeHtml(response.filename)}</span></div><div class="stat-mini-card"><strong>자료 유형</strong><span>${hourly?'시간별 관측자료':'일별 날씨자료'}</span></div><div class="stat-mini-card"><strong>기간</strong><span>${s.date_from||'—'} ~ ${s.date_to||'—'}</span></div><div class="stat-mini-card"><strong>관측지점</strong><span>${numberText(s.stations.length)}개</span></div><div class="stat-mini-card"><strong>전체/정상</strong><span>${numberText(s.total_rows)} / ${numberText(s.valid_rows)}건</span></div><div class="stat-mini-card"><strong>신규/갱신/동일</strong><span>${numberText(s.inserted_rows)} / ${numberText(s.updated_rows)} / ${numberText(s.skipped_rows)}건</span></div><div class="stat-mini-card"><strong>오류/필드 확인</strong><span>${numberText(s.error_rows)} / ${numberText(s.warning_fields)}건</span></div>${hourly?`<div class="stat-mini-card"><strong>같은 값 중복 제외</strong><span>${numberText(s.duplicate_rows||0)}건</span></div><div class="stat-mini-card"><strong>강수 빈칸 → 0mm</strong><span>${numberText(s.precipitation_blank_as_zero||0)}건</span></div><div class="stat-mini-card"><strong>일별 자료 생성 예정</strong><span>${numberText(s.daily_aggregate_days||0)}일${s.partial_days?` · ${numberText(s.partial_days)}일은 20시간 미만이라 제외`:''}</span></div>`:''}</div>${s.source_note?`<p class="muted">파일 정보: ${escapeHtml(s.source_note)}</p>`:''}
  ${hourly?'<div class="aggregation-note">시간별 원본을 그대로 저장하며 11·12시 관측값은 중식, 17·18시 관측값은 석식 시간대 날씨로 함께 저장합니다.</div>':''}<div class="validation-result"><strong>자동 인식 컬럼</strong><div class="placeholder-list">${Object.entries(s.mapped_headers).map(([field,header])=>`<span class="placeholder-chip">${escapeHtml(header)} → ${labels[field]||field}</span>`).join('')}</div>${s.unknown_headers.length?`<p class="muted">사용하지 않은 컬럼: ${s.unknown_headers.map(escapeHtml).join(', ')}</p>`:''}</div>${table}
  ${response.errors.length?`<div class="validation-result"><strong>오류 ${numberText(s.error_rows)}건</strong><p class="muted">오류 행은 제외하고 정상 ${numberText(s.valid_rows)}건만 반영할 수 있습니다.</p>${response.errors.slice(0,20).map(error=>`<p class="form-error">${error.row}행: ${escapeHtml(error.message)}</p>`).join('')}</div>`:''}
  <div class="save-bar"><span class="save-state">분석만으로는 자료가 저장되지 않습니다.</span><button class="primary-button" id="weather-apply" ${s.valid_rows?'':'disabled'}>DB 반영</button></div></div>`;
  $('#weather-apply')?.addEventListener('click',applyWeatherFile);
}
async function previewWeatherFile(){const file=$('#weather-file').files[0];if(!file){toast('날씨자료 파일(weather.nuni.co.kr CSV 또는 기상청 자료)을 선택해 주세요.',true);return;}const fd=new FormData();fd.append('file',file);$('#weather-preview-result').innerHTML='<div class="result-card">파일을 분석하고 있습니다.</div>';const lock=lockUI('날씨자료 파일을 올리고 분석하고 있습니다.');try{renderWeatherPreview(await api('/api/weather/preview',{method:'POST',body:fd}));}catch(e){$('#weather-preview-result').innerHTML=`<div class="result-card"><h3 class="form-error">분석 실패</h3><p>${escapeHtml(e.message)}</p></div>`;toast(e.message,true);}finally{lock.release();}}
async function applyWeatherFile(){const upload=state.weatherUpload;if(!upload?.token)return;if(!confirm(`정상 날씨자료 ${numberText(upload.summary.valid_rows)}건을 반영하시겠습니까? 오류 ${numberText(upload.summary.error_rows)}건은 제외됩니다.`))return;const button=$('#weather-apply');button.disabled=true;button.textContent='반영 중…';const lock=lockUI('날씨자료를 저장하고 있습니다.');try{const response=await api('/api/weather/apply',json('POST',{token:upload.token}));const r=response.result;$('#weather-preview-result').innerHTML=`<div class="result-card"><h3 style="color:var(--ok)">반영 완료</h3><p>반영 일시 ${new Date(response.completed_at).toLocaleString('ko-KR')}</p><div class="stats-mini"><div class="stat-mini-card"><strong>전체</strong><span>${numberText(r.total_rows)}건</span></div><div class="stat-mini-card"><strong>신규 등록</strong><span>${numberText(r.inserted_rows)}건</span></div><div class="stat-mini-card"><strong>기존자료 갱신</strong><span>${numberText(r.updated_rows)}건</span></div><div class="stat-mini-card"><strong>변경 없음</strong><span>${numberText(r.skipped_rows)}건</span></div><div class="stat-mini-card"><strong>오류 제외</strong><span>${numberText(r.error_rows)}건</span></div>${r.duplicate_rows?`<div class="stat-mini-card"><strong>같은 값 중복 제외</strong><span>${numberText(r.duplicate_rows)}건</span></div>`:''}${r.daily_aggregated_days!==undefined?`<div class="stat-mini-card"><strong>일별 자료 생성·갱신</strong><span>${numberText(r.daily_aggregated_days)}일</span></div>`:''}</div></div>`;state.weatherUpload=null;await Promise.all([loadWeatherRecords(),loadMealPeriodWeatherRecords(),loadWeatherUploads()]);toast('날씨자료 반영을 완료했습니다.');}catch(e){button.disabled=false;button.textContent='DB 반영';toast(e.message,true);}finally{lock.release();}}
async function loadWeatherRecords(){const root=$('#weather-records');if(!root)return;const params=new URLSearchParams({offset:String(state.weatherOffset),limit:'50'});const fields={start_date:'#weather-start',end_date:'#weather-end',station:'#weather-station',min_temp:'#weather-min-temp',max_temp:'#weather-max-temp',precipitation:'#weather-rain'};Object.entries(fields).forEach(([key,selector])=>{const value=$(selector)?.value;if(value)params.set(key,value);});try{const data=await api(`/api/weather/records?${params}`);root.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>날짜</th><th>지점</th><th>평균</th><th>최저</th><th>최고</th><th>강수</th><th>습도</th><th>적설</th><th>등록일</th></tr></thead><tbody>${data.items.map(row=>`<tr><td>${row.observation_date}</td><td>${escapeHtml(row.station_name||row.station_id)}<small class="muted"> ${escapeHtml(row.station_id)}</small></td><td>${weatherNumber(row.avg_temp,'℃')}</td><td>${weatherNumber(row.min_temp,'℃')}</td><td>${weatherNumber(row.max_temp,'℃')}</td><td>${weatherNumber(row.precipitation,'mm')}</td><td>${weatherNumber(row.avg_humidity,'%')}</td><td>${weatherNumber(row.snow_depth)}</td><td>${new Date(row.created_at).toLocaleDateString('ko-KR')}</td></tr>`).join('')||'<tr><td colspan="9" class="muted">저장된 날씨자료가 없습니다.</td></tr>'}</tbody></table></div><div class="table-tools"><span class="muted">전체 ${numberText(data.total)}건</span><button class="secondary-button" id="weather-record-prev" ${state.weatherOffset===0?'disabled':''}>이전</button><button class="secondary-button" id="weather-record-next" ${state.weatherOffset+data.limit>=data.total?'disabled':''}>다음</button></div>`;$('#weather-record-prev')?.addEventListener('click',()=>{state.weatherOffset=Math.max(0,state.weatherOffset-50);loadWeatherRecords();});$('#weather-record-next')?.addEventListener('click',()=>{state.weatherOffset+=50;loadWeatherRecords();});}catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}}
async function loadMealPeriodWeatherRecords(){const root=$('#weather-meal-records');if(!root)return;const params=new URLSearchParams({offset:String(state.weatherMealOffset),limit:'50'});const fields={start_date:'#weather-start',end_date:'#weather-end',station:'#weather-station',min_temp:'#weather-min-temp',max_temp:'#weather-max-temp',precipitation:'#weather-rain'};Object.entries(fields).forEach(([key,selector])=>{const value=$(selector)?.value;if(value)params.set(key,value);});try{const data=await api(`/api/weather/meal-period-records?${params}`);root.innerHTML=`<div class="aggregation-note">중식은 11·12시, 석식은 17·18시 관측자료를 사용합니다. 관측 건수는 최대 2건입니다.</div><div class="table-wrap"><table class="data-table"><thead><tr><th>날짜</th><th>배식</th><th>지점</th><th>평균</th><th>최저</th><th>최고</th><th>강수</th><th>습도</th><th>풍속</th><th>관측 건수</th></tr></thead><tbody>${data.items.map(row=>`<tr><td>${row.observation_date}</td><td>${row.meal_type==='LUNCH'?'중식':'석식'}</td><td>${escapeHtml(row.station_name||row.station_id)}<small class="muted"> ${escapeHtml(row.station_id)}</small></td><td>${weatherNumber(row.avg_temp,'℃')}</td><td>${weatherNumber(row.min_temp,'℃')}</td><td>${weatherNumber(row.max_temp,'℃')}</td><td>${weatherNumber(row.precipitation,'mm')}</td><td>${weatherNumber(row.avg_humidity,'%')}</td><td>${weatherNumber(row.avg_wind_speed,'m/s')}</td><td>${numberText(row.sample_count)}/2</td></tr>`).join('')||'<tr><td colspan="10" class="muted">저장된 배식 시간대 날씨자료가 없습니다.</td></tr>'}</tbody></table></div><div class="table-tools"><span class="muted">전체 ${numberText(data.total)}건</span><button class="secondary-button" id="weather-meal-prev" ${state.weatherMealOffset===0?'disabled':''}>이전</button><button class="secondary-button" id="weather-meal-next" ${state.weatherMealOffset+data.limit>=data.total?'disabled':''}>다음</button></div>`;$('#weather-meal-prev')?.addEventListener('click',()=>{state.weatherMealOffset=Math.max(0,state.weatherMealOffset-50);loadMealPeriodWeatherRecords();});$('#weather-meal-next')?.addEventListener('click',()=>{state.weatherMealOffset+=50;loadMealPeriodWeatherRecords();});}catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}}
async function loadWeatherUploads(){const root=$('#weather-uploads');if(!root)return;try{const data=await api(`/api/weather/uploads?offset=${state.weatherHistoryOffset}&limit=20`);root.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>업로드 일시</th><th>파일명</th><th>기간</th><th>지점</th><th>전체</th><th>신규</th><th>갱신</th><th>오류</th><th>상태</th></tr></thead><tbody>${data.items.map(row=>`<tr><td>${new Date(row.created_at).toLocaleString('ko-KR')}</td><td>${escapeHtml(row.original_filename)}</td><td>${row.date_from||'—'} ~ ${row.date_to||'—'}</td><td>${numberText(row.stations.length)}개</td><td>${numberText(row.total_rows)}</td><td>${numberText(row.inserted_rows)}</td><td>${numberText(row.updated_rows)}</td><td>${row.error_rows?`<a href="/api/weather/uploads/${row.id}/errors.csv">${numberText(row.error_rows)}건</a>`:'0건'}</td><td>${escapeHtml(row.status)}</td></tr>`).join('')||'<tr><td colspan="9" class="muted">업로드 이력이 없습니다.</td></tr>'}</tbody></table></div><div class="table-tools"><span class="muted">전체 ${numberText(data.total)}건</span><button class="secondary-button" id="weather-upload-prev" ${state.weatherHistoryOffset===0?'disabled':''}>이전</button><button class="secondary-button" id="weather-upload-next" ${state.weatherHistoryOffset+20>=data.total?'disabled':''}>다음</button></div>`;$('#weather-upload-prev')?.addEventListener('click',()=>{state.weatherHistoryOffset=Math.max(0,state.weatherHistoryOffset-20);loadWeatherUploads();});$('#weather-upload-next')?.addEventListener('click',()=>{state.weatherHistoryOffset+=20;loadWeatherUploads();});}catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}}

function renderActualMealUploadView(root){
  root.innerHTML=`<div class="narrow-card">
    <h2>식수 정보 업로드</h2>
    <p>‘실제식수정보’ 시트의 일자·중식·석식·특이사항을 검증한 뒤 기존 배식정보의 실제식수에 반영합니다. 파일 검증만으로는 DB가 변경되지 않습니다.</p>
    <div class="upload-zone"><input id="actual-meal-file" type="file" accept=".xlsx" aria-label="식수 정보 XLSX 파일"><button id="actual-meal-preview" class="secondary-button" type="button">파일 검증</button></div>
    <div id="actual-meal-result"></div>
  </div>`;
  $('#actual-meal-preview').addEventListener('click',previewActualMealUpload);
}

function renderActualMealSummary(summary){
  return `<div class="result-card actual-meal-summary"><h3>검증 요약</h3><div class="stats-mini">
    <div class="stat-mini-card"><strong>파일/시트</strong><span>${escapeHtml(summary.filename||'')} · ${escapeHtml(summary.sheet_name||'')}</span></div>
    <div class="stat-mini-card"><strong>원본 행/기간</strong><span>${numberText(summary.source_row_count)}행 · ${summary.start_date||'-'} ~ ${summary.end_date||'-'}</span></div>
    <div class="stat-mini-card"><strong>중식</strong><span>${numberText(summary.lunch_input_count)}건 · ${numberText(summary.lunch_sum)}명</span></div>
    <div class="stat-mini-card"><strong>석식</strong><span>${numberText(summary.dinner_input_count)}건 · ${numberText(summary.dinner_sum)}명</span></div>
    <div class="stat-mini-card"><strong>반영 후보</strong><span>${numberText(summary.candidate_count)}건</span></div>
    <div class="stat-mini-card"><strong>신규/수정/변경 없음</strong><span>${numberText(summary.new_count)} / ${numberText(summary.update_count)} / ${numberText(summary.unchanged_count)}</span></div>
    <div class="stat-mini-card"><strong>신규 배식 생성</strong><span>${numberText(summary.service_created_count||0)}건</span></div>
    <div class="stat-mini-card"><strong>제외/오류</strong><span>${numberText(summary.excluded_count)} / ${numberText(summary.error_count)}</span></div>
  </div></div>`;
}

function renderActualMealRows(){
  const result=$('#actual-meal-result');const upload=state.actualMealUpload;if(!result||!upload)return;
  const rows=upload.rows||[];const pageSize=50;const page=upload.page||0;const pageCount=Math.max(1,Math.ceil(rows.length/pageSize));const visible=rows.slice(page*pageSize,(page+1)*pageSize);
  const statusClass={신규:'badge-ok',수정:'badge-warn','변경 없음':'badge-inactive',오류:'badge-fail',제외:'badge-inactive','신규 배식':'badge-ok'};
  const table=`<div class="table-wrap"><table class="data-table"><thead><tr><th>Excel 행</th><th>일자</th><th>배식유형</th><th>업로드 실제식수</th><th>기존 DB 실제식수</th><th>반영 후 실제식수</th><th>특이사항</th><th>처리 예정 상태</th><th>오류 내용</th></tr></thead><tbody>${visible.map(row=>`<tr><td>${row.excel_row}</td><td>${escapeHtml(row.date||'-')}</td><td>${escapeHtml(row.meal_type_name||row.meal_type||'-')}</td><td>${numberText(row.upload_count)}</td><td>${row.existing_count===null||row.existing_count===undefined?'-':numberText(row.existing_count)}</td><td>${row.error?'-':numberText(row.upload_count)}</td><td>${escapeHtml(row.note||'')}</td><td><span class="badge ${statusClass[row.status]||''}">${escapeHtml(row.status||'-')}${row.service_created?' ⚡':''}</span></td><td class="form-error">${escapeHtml(row.error||'')}</td></tr>`).join('')}</tbody></table></div>`;
  const canApply=!upload.errors?.length&&upload.summary.error_count===0&&upload.token;
  const pager=`<div class="table-tools"><span class="muted">${rows.length?`${page*pageSize+1}~${Math.min((page+1)*pageSize,rows.length)}행 / 전체 ${rows.length}행`: '표시할 데이터가 없습니다.'}</span><button class="secondary-button" id="actual-meal-prev" ${page<=0?'disabled':''}>이전</button><button class="secondary-button" id="actual-meal-next" ${page>=pageCount-1?'disabled':''}>다음</button><button class="primary-button" id="actual-meal-apply" ${canApply?'':'disabled'}>DB 반영</button></div>`;
  result.innerHTML=renderActualMealSummary({...upload.summary,filename:upload.filename})+pager+table;
  $('#actual-meal-prev')?.addEventListener('click',()=>{upload.page=Math.max(0,page-1);renderActualMealRows();});
  $('#actual-meal-next')?.addEventListener('click',()=>{upload.page=Math.min(pageCount-1,page+1);renderActualMealRows();});
  $('#actual-meal-apply')?.addEventListener('click',applyActualMealUpload);
}

let actualMealRequestInFlight=false; // double-click guard for actual-meal preview/apply
async function previewActualMealUpload(){
  if(actualMealRequestInFlight)return;
  const file=$('#actual-meal-file').files[0];if(!file){toast('식수 정보 XLSX 파일을 선택해 주세요.',true);return;}
  actualMealRequestInFlight=true;
  const previewButton=$('#actual-meal-preview');const previewLabel=previewButton?previewButton.textContent:'';if(previewButton){previewButton.disabled=true;previewButton.textContent='검증 중…';}
  const data=new FormData();data.append('file',file);const result=$('#actual-meal-result');result.innerHTML='<div class="result-card">파일을 검증하고 있습니다.</div>';
  const lock=lockUI('식수 정보 파일을 올리고 검증하고 있습니다.');
  try{const response=await api('/api/setup/actual-meals/preview',{method:'POST',body:data});state.actualMealUpload={...response,filename:file.name,page:0};renderActualMealRows();}
  catch(e){result.innerHTML=`<div class="result-card"><h3 class="form-error">검증 실패</h3><p>${escapeHtml(e.message)}</p></div>`;toast(e.message,true);}
  finally{lock.release();actualMealRequestInFlight=false;const b=$('#actual-meal-preview');if(b){b.disabled=false;b.textContent=previewLabel||'파일 검증';}}
}

async function applyActualMealUpload(){
  if(actualMealRequestInFlight)return;
  const upload=state.actualMealUpload;if(!upload?.token)return;
  if(!confirm(`검증된 ${numberText(upload.summary.candidate_count)}건의 식수 정보를 DB에 반영하시겠습니까? 파일에 없는 기존 데이터는 유지됩니다.`))return;
  actualMealRequestInFlight=true;
  const previewButton=$('#actual-meal-preview');if(previewButton)previewButton.disabled=true;
  const button=$('#actual-meal-apply');if(button){button.disabled=true;button.textContent='반영 중…';}
  const lock=lockUI('식수 정보를 저장하고 있습니다.');
  try{const response=await api('/api/setup/actual-meals/apply',json('POST',{token:upload.token}));const result=response.result;const v=response.verification||{};$('#actual-meal-result').innerHTML=`<div class="result-card"><h3 style="color:var(--ok)">✓ 반영 완료</h3><p>반영 일시 ${new Date(response.completed_at).toLocaleString('ko-KR')}</p><div class="stats-mini"><div class="stat-mini-card"><strong>전체 반영 후보</strong><span>${numberText(result.candidate_count)}건</span></div><div class="stat-mini-card"><strong>신규 등록</strong><span>${numberText(result.new_count)}건</span></div><div class="stat-mini-card"><strong>수정</strong><span>${numberText(result.update_count)}건</span></div><div class="stat-mini-card"><strong>변경 없음</strong><span>${numberText(result.unchanged_count)}건</span></div><div class="stat-mini-card"><strong>신규 배식 생성</strong><span>${numberText(result.service_created_count||0)}건</span></div><div class="stat-mini-card"><strong>제외</strong><span>${numberText(result.excluded_count)}건</span></div><div class="stat-mini-card"><strong>실패</strong><span>${numberText(result.failed_count)}건</span></div></div><div class="result-card" style="margin-top:12px;background:#eef8f3;border-color:#cfe8db"><h4>반영 검증</h4><p>DB 전체 실제식수 기록: <strong>${numberText(v.total_actual_records||0)}건</strong> / 전체 배식정보: <strong>${numberText(v.total_services||0)}건</strong></p><p class="muted">주간 식단표에서 반영된 식수를 확인할 수 있습니다.</p></div><div class="inline-form" style="margin-top:12px"><button class="secondary-button" id="actual-meal-goto-workspace">주간 식단표에서 확인</button><button class="secondary-button" id="actual-meal-reupload">추가 업로드</button></div></div>`;toast('식수 정보 반영을 완료했습니다.');$('#actual-meal-goto-workspace')?.addEventListener('click',()=>{switchView('workspace');});$('#actual-meal-reupload')?.addEventListener('click',()=>{state.actualMealUpload=null;renderActualMealUploadView($('#master-data-content'));});}
  catch(e){if(button){button.disabled=false;button.textContent='DB 반영';}toast(e.message,true);}
  finally{lock.release();actualMealRequestInFlight=false;const b=$('#actual-meal-preview');if(b)b.disabled=false;}
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
  const data=await api('/api/master/ingredients?active=true&limit=1000');
  state.ingredientCache=data.items||data;
  return state.ingredientCache;
}

let _menuRenderToken=0;
async function renderMenusMaster(root,q=state.masterMenuQuery||''){const token=++_menuRenderToken;
  const data=await api(`/api/master/menus?q=${encodeURIComponent(q)}&offset=0&limit=50`); state.masterMenuQuery=q; state.masterMenuOffset=0; state.masterMenuHasMore=false; state.masterMenuLoading=false; const rows=data.items; state.masterMenuHasMore=data.has_more;
  if(token!==_menuRenderToken)return;
  const oldInput=$('#master-search');const hadFocus=document.activeElement===oldInput;const curVal=oldInput?.value??q;const curCursor=oldInput?.selectionStart;const curScroll=oldInput?.scrollTop;
  root.innerHTML=`<div class="master-split">
    <section class="master-list-panel">
      <div class="table-tools"><input id="master-search" placeholder="메뉴명 입력 후 Enter 또는 조회" value="${escapeHtml(curVal)}"><button class="primary-button" id="master-search-btn">조회</button><button class="secondary-button" id="new-menu">＋ 메뉴</button></div>
      <div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>메뉴명</th><th>역할</th><th>레시피</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-menu-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.role)}</td><td>${r.recipe_count}개</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div>
    </section>
    <aside id="master-editor" class="master-editor-panel"></aside>
  </div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  bindSearchSubmit($('#master-search'),$('#master-search-btn'),value=>renderMenusMaster(root,value.trim()));
  $('#new-menu').addEventListener('click',()=>{state.masterSelectionId=null;state.selectedRecipeId=null;state.masterMenuDetailTab='recipe';renderMenuMasterPanel(null);});
  const menuTable=$('.master-list-wrap table',root); menuTable.addEventListener('click',e=>{ const row=e.target.closest('tr[data-menu-master]'); if(!row)return; state.masterSelectionId=Number(row.dataset.menuMaster); state.selectedRecipeId=null; state.masterMenuDetailTab='recipe'; state.masterMenuHistory={menuId:null,items:[],offset:0,total:0,hasMore:false,loading:false,error:'',snapshotCache:{},expandedSnapshotId:null};state.masterHistoryFilter=''; $$('[data-menu-master]',menuTable).forEach(x=>x.classList.toggle('selected-row',x===row)); renderMenuMasterPanel(state.masterSelectionId); }); const menuWrap=$('.master-list-wrap',root); menuWrap.addEventListener('scroll',()=>{ if(!state.masterMenuHasMore||state.masterMenuLoading)return; if(menuWrap.scrollTop+menuWrap.clientHeight>=menuWrap.scrollHeight-80) loadMoreMasterMenus(); });
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
  const detailTab=id?(state.masterMenuDetailTab||'recipe'):'recipe';
  await loadIngredientCache();
  const header=`<div class="master-menu-workspace-header"><div><h3>${escapeHtml(id?data.name:'새 메뉴')}</h3><small>${id?`${escapeHtml(data.role)} · ${data.active?'사용':'미사용'}`:'메뉴 기본정보를 입력하세요.'}</small></div>${detailTab==='recipe'?`<button class="primary-button" id="save-master-menu">${id?'메뉴 정보 저장':'메뉴 등록'}</button>`:''}</div>`;
  const tabs=id?`<div class="master-menu-detail-tabs" role="tablist"><button type="button" class="master-menu-detail-tab ${detailTab==='recipe'?'active':''}" data-master-menu-detail="recipe" role="tab" aria-selected="${detailTab==='recipe'}">기본정보·레시피</button><button type="button" class="master-menu-detail-tab ${detailTab==='history'?'active':''}" data-master-menu-detail="history" role="tab" aria-selected="${detailTab==='history'}">사용 이력</button></div>`:'';
  const recipeContent=`<section class="master-menu-section"><div class="master-section-heading"><div><h4>레시피</h4><small>메뉴에 적용할 기준 레시피를 관리합니다.</small></div><button class="secondary-button" id="new-recipe">＋ 새 레시피</button></div><div class="recipe-manager">
      <div class="recipe-list-column"><div class="recipe-list">${recipes.map(r=>`<button class="recipe-list-item ${recipe?.id===r.id?'active':''}" data-recipe-id="${r.id}"><div class="recipe-list-item-head"><strong>${escapeHtml(recipeNameWithoutVersion(r.name))}</strong>${r.is_default?'<em class="recipe-default-label">기본</em>':''}</div><span>재료 ${r.ingredient_count}개${r.active?'':' · 미사용'}</span></button>`).join('')||'<p class="muted">등록된 레시피가 없습니다.</p>'}</div></div>
      <div id="recipe-editor" class="recipe-editor-column">${recipe?recipeEditorHtml(recipe):'<div class="empty-editor">새 레시피를 등록해 주세요.</div>'}</div>
    </div></section>`;
  const content=detailTab==='history'?'<div id="master-menu-history-root" class="master-menu-history-root"><div class="master-history-loading">사용 이력을 불러오는 중...</div></div>':`<div class="master-menu-detail-content"><section class="master-menu-section"><div class="master-section-heading"><h4>메뉴 기본정보</h4></div><div class="menu-basic-fields"><div class="menu-basic-name-row"><label class="field">메뉴명<input id="mm-name" value="${escapeHtml(data.name)}"></label><label class="field">통계 집계명<input id="mm-canonical" value="${escapeHtml(data.canonical_name||data.name)}"></label></div><div class="menu-meta-row"><label class="inline-field">메뉴 역할<select id="mm-role">${state.codes.menu_roles.map(x=>`<option ${x===data.role?'selected':''}>${x}</option>`).join('')}</select></label><label class="inline-field">사용 여부<select id="mm-active"><option value="true" ${data.active?'selected':''}>사용</option><option value="false" ${!data.active?'selected':''}>미사용</option></select></label>${id?'<div class="menu-delete-action"><button type="button" class="danger-button" id="archive-menu">메뉴 삭제</button></div>':''}</div></div></section>${id?recipeContent:'<p class="muted">메뉴를 먼저 등록하면 레시피를 관리할 수 있습니다.</p>'}</div>`;
  panel.innerHTML=header+tabs+content+`<datalist id="ingredient-options">${state.ingredientCache.map(i=>`<option value="${escapeHtml(i.name)}"></option>`).join('')}</datalist>`;
  $$('[data-master-menu-detail]').forEach(button=>button.addEventListener('click',()=>{state.masterMenuDetailTab=button.dataset.masterMenuDetail;renderMenuMasterPanel(id);}));
  const saveButton=$('#save-master-menu');
  if(saveButton)saveButton.addEventListener('click',async()=>{try{const body={name:$('#mm-name').value,canonical_name:$('#mm-canonical').value,role:$('#mm-role').value,active:$('#mm-active').value==='true'};const result=id?await api(`/api/master/menus/${id}`,json('PUT',body)):await api('/api/master/menus',json('POST',body));state.masterSelectionId=id||result.id;state.selectedRecipeId=null;state.masterMenuDetailTab='recipe';toast(id?'메뉴 정보를 저장했습니다.':'메뉴를 등록했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
  if(id){
    if(detailTab==='history')loadMasterMenuHistory(id);
    $('#archive-menu')?.addEventListener('click',async()=>{if(!confirm('메뉴를 삭제(미사용 처리)할까요? 과거 식단 기록은 유지됩니다.'))return;try{await api(`/api/master/menus/${id}`,{method:'DELETE'});state.masterSelectionId=null;state.selectedRecipeId=null;state.masterMenuDetailTab='recipe';toast('메뉴를 삭제 처리했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
    if(detailTab==='recipe'){$('#new-recipe').addEventListener('click',()=>{state.selectedRecipeId='new';renderMenuMasterPanel(id);});$$('[data-recipe-id]').forEach(button=>button.addEventListener('click',()=>{state.selectedRecipeId=Number(button.dataset.recipeId);renderMenuMasterPanel(id);}));if(recipe)bindRecipeEditor(id,recipe);}
  }
}

async function loadMasterMenuHistory(menuId,append=false){
  const history=state.masterMenuHistory;
  if(history.loading)return;
  if(!append){history.items=[];history.offset=0;history.total=0;history.hasMore=false;history.error='';}
  history.menuId=menuId;history.loading=true;const requestId=(history.requestId||0)+1;history.requestId=requestId;renderMasterMenuHistory();
  try{
    const params=new URLSearchParams({offset:String(history.offset),limit:'20'});
    if(state.masterHistoryFilter)params.set('meal_type',state.masterHistoryFilter);
    const data=await api(`/api/master/menus/${menuId}/usage-history?${params}`);
    if(state.masterMenuHistory!==history||history.menuId!==menuId||history.requestId!==requestId)return;
    history.items=append?history.items.concat(data.items||[]):data.items||[];
    history.offset=history.items.length;history.total=data.total||0;history.hasMore=Boolean(data.has_more);history.error='';
  }catch(e){history.error=e.message;}
  history.loading=false;renderMasterMenuHistory();
}
function renderMasterMenuHistory(){
  const root=$('#master-menu-history-root');const history=state.masterMenuHistory;if(!root)return;
  if(history.error){root.innerHTML=`<div class="master-history-error">사용 이력을 불러오지 못했습니다.<small>${escapeHtml(history.error)}</small><button class="secondary-button" id="master-history-retry">다시 시도</button></div>`;$('#master-history-retry').addEventListener('click',()=>loadMasterMenuHistory(history.menuId));return;}
  const filters=`<div class="master-history-toolbar"><div class="master-history-filters"><button data-history-filter="" class="${!state.masterHistoryFilter?'active':''}">전체</button><button data-history-filter="LUNCH" class="${state.masterHistoryFilter==='LUNCH'?'active':''}">중식</button><button data-history-filter="DINNER" class="${state.masterHistoryFilter==='DINNER'?'active':''}">석식</button></div><strong>총 ${history.total}회 사용</strong></div>`;
  if(history.loading&&!history.items.length){root.innerHTML=filters+'<div class="master-history-loading">사용 이력을 불러오는 중...</div>';return;}
  if(!history.items.length){root.innerHTML=filters+'<div class="master-history-empty">사용 이력이 없습니다.<small>이 메뉴가 식단에 사용되면 이곳에서 확인할 수 있습니다.</small></div>';return;}
  root.innerHTML=filters+`<div class="master-history-list">${history.items.map(renderMasterHistoryCard).join('')}</div>${history.hasMore?'<button class="secondary-button master-history-more" id="master-history-more">더 보기</button>':''}`;
  $$('[data-history-filter]',root).forEach(button=>button.addEventListener('click',()=>{state.masterHistoryFilter=button.dataset.historyFilter;loadMasterMenuHistory(history.menuId);}));
  $$('[data-history-menu]',root).forEach(button=>button.addEventListener('click',()=>loadMasterSnapshot(Number(button.dataset.historyMenu),button.closest('.master-history-card'))));
  $('#master-history-more')?.addEventListener('click',()=>loadMasterMenuHistory(history.menuId,true));
}
function recipeNameWithoutVersion(name){return String(name||'').trim().replace(/\s+(?:v|ver\.?|버전)\s*\d+$/i,'').trim();}
function renderMasterHistoryCard(item){
  const date=new Date(item.date).toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',weekday:'short'});
  const targetId=item.target_meal_service_menu_id;
  const mealLabel=escapeHtml({LUNCH:'중식',DINNER:'석식'}[item.meal_type]||item.meal_type);
  const actualCount=item.actual_count==null?'-':`${numberText(item.actual_count)}명`;
  const recipeName=item.target_recipe?.name?recipeNameWithoutVersion(item.target_recipe.name):'';
  return `<article class="master-history-card"><header><strong>${date} · ${mealLabel} · 실제 ${actualCount}</strong>${recipeName?`<span class="master-history-recipe">${escapeHtml(recipeName)}</span>`:''}</header><div class="master-history-menus">${item.menus.map(menu=>`<button type="button" class="master-history-menu ${menu.meal_service_menu_id===targetId?'target':''}" data-history-menu="${menu.meal_service_menu_id}">${menu.is_representative?'<span class="representative-mark" title="메인 메뉴">★</span>':''}${escapeHtml(menu.name)}</button>`).join('')}</div><div class="master-history-snapshot" data-snapshot-for="${item.meal_service_id}"></div></article>`;
}
async function loadMasterSnapshot(menuId,card){
  const history=state.masterMenuHistory;history.expandedSnapshotId=menuId;
  const targetCard=card.closest('.master-history-card');if(!targetCard)return;
  $$('.master-history-snapshot').forEach(el=>{if(el!==$('.master-history-snapshot',targetCard))el.innerHTML='';});
  const root=$('.master-history-snapshot',targetCard);root.innerHTML='<div class="master-snapshot-loading">재료 정보를 불러오는 중...</div>';
  if(history.snapshotCache?.[menuId]){renderMasterSnapshot(root,history.snapshotCache[menuId]);return;}
  history.snapshotCache=history.snapshotCache||{};
  try{const data=await api(`/api/master/meal-service-menus/${menuId}/snapshot`);if(history.expandedSnapshotId!==menuId)return;history.snapshotCache[menuId]=data;renderMasterSnapshot(root,data);}catch(e){root.innerHTML=`<div class="master-snapshot-error">재료 정보를 불러오지 못했습니다.</div>`;}
}
function renderMasterSnapshot(root,data){
  const canSave=data.menu_id===state.masterSelectionId;
  root.innerHTML=`<div class="master-snapshot-title">${escapeHtml(data.menu_name)} · 당시 사용 재료</div><div class="master-snapshot-table"><div class="master-snapshot-row head"><span>재료</span><span>실제 사용량</span><span>100인 수량</span></div>${data.ingredients.length?data.ingredients.map(item=>`<div class="master-snapshot-row"><span>${escapeHtml(item.name)}</span><span>${formatSnapshotValue(item.quantity_total,item.unit)}</span><span>${formatSnapshotValue(item.quantity_per_100,item.unit)}</span></div>`).join(''):'<div class="master-snapshot-empty">저장된 재료가 없습니다.</div>'}</div>${canSave?'<div class="master-snapshot-actions"><button type="button" class="secondary-button" id="save-snapshot-recipe">이 구성으로 레시피 저장</button></div>':''}`;
  if(canSave)$('#save-snapshot-recipe').addEventListener('click',()=>openSnapshotRecipeDialog(data));
}
function formatSnapshotValue(value,unit){return `${value==null?'-':Number(value).toLocaleString('ko-KR',{maximumFractionDigits:3})} ${unit||''}`.trim();}

async function openSnapshotRecipeDialog(snapshot){
  try{
    const menu=await api(`/api/master/menus/${snapshot.menu_id}`);
    renderSnapshotRecipeDialog(snapshot,menu);
  }catch(e){toast(e.message,true);}
}
function renderSnapshotRecipeDialog(snapshot,menu){
  const currentRecipeId=snapshot.recipe?.recipe_id;
  const recipes=(menu.recipes||[]).filter(recipe=>recipe.active);
  modal(`<div class="modal-head"><h3>이 구성으로 레시피 저장</h3><button class="icon-button" onclick="closeModal()">×</button></div><div class="modal-info"><strong>기준 식단</strong><br>${snapshot.date} · ${escapeHtml({LUNCH:'중식',DINNER:'석식'}[snapshot.meal_type]||snapshot.meal_type)} · ${escapeHtml(snapshot.menu_name)} · 계획 ${numberText(snapshot.planned_count)}명</div><p class="form-hint">이 식단에 저장된 100인 기준 재료를 사용합니다.</p><div class="snapshot-recipe-form"><label><input type="radio" name="snapshot-recipe-mode" value="update"> 기존 레시피 업데이트</label><label><input type="radio" name="snapshot-recipe-mode" value="create" checked> 새 레시피 생성</label><label class="field snapshot-target-field hidden">업데이트할 레시피<select id="snapshot-target-recipe"><option value="">레시피 선택</option>${recipes.map(recipe=>`<option value="${recipe.id}" ${recipe.id===currentRecipeId?'selected':''}>${escapeHtml(recipe.name)}</option>`).join('')}</select></label><label class="field snapshot-name-field">새 레시피 이름<input id="snapshot-recipe-name" maxlength="120" value="" placeholder="새 레시피 이름을 입력하세요"></label><label class="snapshot-default-field"><input id="snapshot-make-default" type="checkbox"> 생성 후 기본 레시피로 지정</label></div><div id="snapshot-recipe-error" class="form-error" aria-live="polite"></div><div class="save-bar"><button class="ghost-button" id="snapshot-recipe-cancel">취소</button><button class="primary-button" id="snapshot-recipe-next">다음</button></div>`);
  const updateForm=()=>{const mode=$('input[name="snapshot-recipe-mode"]:checked')?.value;$('.snapshot-target-field')?.classList.toggle('hidden',mode!=='update');$('.snapshot-name-field')?.classList.toggle('hidden',mode!=='create');$('.snapshot-default-field')?.classList.toggle('hidden',mode!=='create');};
  $$('input[name="snapshot-recipe-mode"]').forEach(input=>input.addEventListener('change',updateForm));
  $('#snapshot-recipe-cancel').addEventListener('click',closeModal);$('#snapshot-recipe-next').addEventListener('click',()=>previewSnapshotRecipe(snapshot,menu));updateForm();
}
async function previewSnapshotRecipe(snapshot,menu){
  const mode=$('input[name="snapshot-recipe-mode"]:checked')?.value;const targetRecipeId=Number($('#snapshot-target-recipe')?.value||0)||null;const recipeName=$('#snapshot-recipe-name')?.value.trim()||null;const makeDefault=$('#snapshot-make-default')?.checked||false;const error=$('#snapshot-recipe-error');if(error)error.textContent='';
  if(mode==='update'&&!targetRecipeId){if(error)error.textContent='업데이트할 레시피를 선택해 주세요.';return;}if(mode==='create'&&!recipeName){if(error)error.textContent='새 레시피 이름을 입력해 주세요.';return;}
  const button=$('#snapshot-recipe-next');if(button){button.disabled=true;button.textContent='비교 중...';}
  try{const preview=await api(`/api/master/menus/${snapshot.menu_id}/recipes/from-snapshot/preview`,json('POST',{meal_service_menu_id:snapshot.meal_service_menu_id,mode,target_recipe_id:targetRecipeId,recipe_name:recipeName,make_default:$('#snapshot-make-default')?.checked||false}));renderSnapshotRecipePreview(snapshot,menu,preview,mode,targetRecipeId,recipeName,makeDefault,preview.recipe_fingerprint);}catch(e){if(error)error.textContent=e.message;if(button){button.disabled=false;button.textContent='다음';}}
}
function renderSnapshotRecipePreview(snapshot,menu,preview,mode,targetRecipeId,recipeName,makeDefault,recipeFingerprint){
  const summary=preview.diff?.summary;const warnings=preview.warnings||[];const diffItems=preview.diff?.items||[];
  const diffHtml=mode==='create'?`<div class="recipe-diff-list"><strong>Snapshot 재료 ${preview.snapshot_ingredients?.length||0}개</strong>${(preview.snapshot_ingredients||[]).map(item=>`<div class="recipe-diff-item"><strong>${escapeHtml(item.name)}</strong><small>${formatSnapshotValue(item.quantity_per_100,item.unit)}</small></div>`).join('')}</div>`:diffItems.length?`<div class="recipe-diff-list">${diffItems.map(item=>`<div class="recipe-diff-item"><span>${item.type==='added'?'추가':item.type==='removed'?'제거':'변경'}</span><strong>${escapeHtml(item.name)}</strong><small>${item.current?formatSnapshotValue(item.current.quantity_per_100,item.current.unit):'-'} → ${item.snapshot?formatSnapshotValue(item.snapshot.quantity_per_100,item.snapshot.unit):'-'}</small></div>`).join('')}</div>`:'<p class="form-hint">현재 레시피와 동일합니다.</p>';
  const warningHtml=warnings.length?`<div class="snapshot-warning-list">${warnings.map(w=>`<div>⚠ ${escapeHtml(w.message)}</div>`).join('')}</div>`:'';
  modal(`<div class="modal-head"><h3>레시피 반영 확인</h3><button class="icon-button" onclick="closeModal()">×</button></div><div class="modal-info"><strong>${escapeHtml(snapshot.menu_name)}</strong><br>${snapshot.date} · ${escapeHtml({LUNCH:'중식',DINNER:'석식'}[snapshot.meal_type]||snapshot.meal_type)} · ${mode==='update'?'기존 레시피 업데이트':'새 레시피 생성'}</div>${summary?`<p class="form-hint">추가 ${summary.added}개 · 변경 ${summary.changed}개 · 제거 ${summary.removed}개</p>`:''}${diffHtml}${warningHtml}<p class="form-hint">이 작업은 기준 레시피를 변경하며, 과거 식단 기록은 변경하지 않습니다.</p><div id="snapshot-apply-error" class="form-error" aria-live="polite"></div><div class="save-bar"><button class="ghost-button" id="snapshot-preview-cancel">취소</button><button class="primary-button" id="snapshot-apply" ${preview.can_apply?'':'disabled'}>${mode==='update'?'레시피 업데이트':'새 레시피 생성'}</button></div>`);
  $('#snapshot-preview-cancel').addEventListener('click',()=>renderSnapshotRecipeDialog(snapshot,menu));
  $('#snapshot-apply').addEventListener('click',()=>applySnapshotRecipe(snapshot,mode,targetRecipeId,recipeName,makeDefault,recipeFingerprint));
}
async function applySnapshotRecipe(snapshot,mode,targetRecipeId,recipeName,makeDefault,recipeFingerprint){
  const button=$('#snapshot-apply'),error=$('#snapshot-apply-error');if(button){button.disabled=true;button.textContent=mode==='update'?'업데이트 중...':'생성 중...';}
  try{const url=mode==='update'?`/api/master/menus/${snapshot.menu_id}/recipes/${targetRecipeId}/apply-snapshot`:`/api/master/menus/${snapshot.menu_id}/recipes/from-snapshot`;const body=mode==='update'?{meal_service_menu_id:snapshot.meal_service_menu_id,mode:'update',expected_recipe_fingerprint:recipeFingerprint}:{meal_service_menu_id:snapshot.meal_service_menu_id,recipe_name:recipeName,make_default:makeDefault};const result=await api(url,json('POST',body));state.masterSelectionId=snapshot.menu_id;state.selectedRecipeId=result.id;state.masterMenuDetailTab='recipe';closeModal();loadMaster();toast(`${result.name}을 저장했습니다.`);}catch(e){if(error)error.textContent=e.message;if(button){button.disabled=false;button.textContent=mode==='update'?'레시피 업데이트':'새 레시피 생성';}}
}

function recipeEditorHtml(recipe){
  return `<div class="recipe-editor-head"><div><h4>${recipe.id?escapeHtml(recipeNameWithoutVersion(recipe.name||'레시피')):'새 레시피'}</h4><small>${recipe.id?`${recipe.is_default?'기본 · ':''}${recipe.active?'사용':'미사용'}`:'재료 구성이 달라질 때만 새 레시피를 만듭니다.'}</small></div></div>
  <div class="recipe-edit-meta-row"><label class="field">레시피명<input id="recipe-name" value="${escapeHtml(recipe.name||'')}"></label><label class="field recipe-status-field">상태<select id="recipe-active"><option value="true" ${recipe.active?'selected':''}>사용</option><option value="false" ${!recipe.active?'selected':''}>미사용</option></select></label><label class="recipe-default-inline"><input id="recipe-default" type="checkbox" ${recipe.is_default?'checked':''}> 식단 추가 시 기본 선택</label></div>
  <div class="grid-help">엑셀에서 <strong>재료명 / 100인 수량 / 단위 / 주재료</strong> 열을 복사한 뒤 첫 번째 재료 칸에 붙여넣을 수 있습니다.</div>
  <div id="recipe-grid-container"></div>
  <div class="panel-action-row"><button class="ghost-button" id="add-recipe-row">＋ 행 추가</button></div>
  <label class="field">레시피 비고<textarea id="recipe-note">${escapeHtml(recipe.note||'')}</textarea></label>
  <div class="save-bar recipe-save-bar">${recipe.id?'<button class="danger-button" id="archive-recipe">레시피 삭제</button>':''}<span class="save-state">재료 구성은 수량과 무관하게 레시피를 구분합니다.</span><button class="primary-button" id="save-recipe">레시피 저장</button></div>`;
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
  const data=await api(`/api/master/ingredients?q=${encodeURIComponent(q)}&offset=0&limit=50`); state.masterIngredientQuery=q; state.masterIngredientOffset=0; state.masterIngredientHasMore=false; state.masterIngredientLoading=false; const rows=data.items; state.masterIngredientHasMore=data.has_more;
  if(token!==_ingredientRenderToken)return;
  const oldInput=$('#master-search');const hadFocus=document.activeElement===oldInput;const curVal=oldInput?.value??q;const curCursor=oldInput?.selectionStart;const curScroll=oldInput?.scrollTop;
  root.innerHTML=`<div class="master-split">
    <section class="master-list-panel"><div class="table-tools"><input id="master-search" placeholder="재료명 입력 후 Enter 또는 조회" value="${escapeHtml(curVal)}"><button class="primary-button" id="master-search-btn">조회</button><button class="secondary-button" id="new-ingredient">＋ 재료</button></div><div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>재료명</th><th>통계분석군</th><th>단위</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-ingredient-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.stat_group)}</td><td>${escapeHtml(r.default_unit||'')}</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div></section>
    <aside id="master-editor" class="master-editor-panel"></aside></div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  bindSearchSubmit($('#master-search'),$('#master-search-btn'),value=>renderIngredientsMaster(root,value.trim()));
  $('#new-ingredient').addEventListener('click',()=>{state.masterSelectionId=null;state.masterIngredientDetailTab='info';state.masterIngredientUsageQuery='';state.masterIngredientUsage={ingredientId:null,items:[],offset:0,total:0,hasMore:false,loading:false,error:''};renderIngredientMasterPanel();});
  const ingredientTable=$('.master-list-wrap table',root); ingredientTable.addEventListener('click',e=>{ const row=e.target.closest('tr[data-ingredient-master]'); if(!row)return; state.masterSelectionId=Number(row.dataset.ingredientMaster); state.masterIngredientDetailTab='info';state.masterIngredientUsageQuery='';state.masterIngredientUsage={ingredientId:null,items:[],offset:0,total:0,hasMore:false,loading:false,error:''}; $$('[data-ingredient-master]',ingredientTable).forEach(x=>x.classList.toggle('selected-row',x===row)); renderIngredientMasterPanel(state.masterSelectionId); }); const ingredientWrap=$('.master-list-wrap',root); ingredientWrap.addEventListener('scroll',()=>{ if(!state.masterIngredientHasMore||state.masterIngredientLoading)return; if(ingredientWrap.scrollTop+ingredientWrap.clientHeight>=ingredientWrap.scrollHeight-80) loadMoreMasterIngredients(); });
  if(state.masterSelectionId&&rows.some(r=>r.id===state.masterSelectionId))renderIngredientMasterPanel(state.masterSelectionId);else $('#master-editor').innerHTML='<div class="empty-editor">왼쪽에서 재료를 선택하거나 새 재료를 등록하세요.</div>';
}

async function renderIngredientMasterPanel(id=null){
  const panel=$('#master-editor');let data={name:'',stat_group:'기타',default_unit:'',kg_factor:null,analysis_excluded:false,active:true,aliases:[]};if(id)data=await api(`/api/master/ingredients/${id}`);
  const detailTab=id?(state.masterIngredientDetailTab||'info'):'info';
  const header=`<div class="master-ingredient-workspace-header"><div><h3>${escapeHtml(id?data.name:'새 재료')}</h3><small>${id?`${escapeHtml(data.stat_group)} · ${data.active?'사용':'미사용'}`:'재료 기본정보를 입력하세요.'}</small></div>${detailTab==='info'?`<button class="primary-button" id="save-master-ingredient">${id?'재료 정보 저장':'재료 등록'}</button>`:''}</div>`;
  const tabs=id?`<div class="master-ingredient-detail-tabs" role="tablist"><button type="button" class="master-ingredient-detail-tab ${detailTab==='info'?'active':''}" data-master-ingredient-detail="info" role="tab" aria-selected="${detailTab==='info'}">재료 정보</button><button type="button" class="master-ingredient-detail-tab ${detailTab==='usage'?'active':''}" data-master-ingredient-detail="usage" role="tab" aria-selected="${detailTab==='usage'}">사용 메뉴</button></div>`:'';
  const info=`<div class="master-ingredient-detail-content"><section class="master-menu-section"><div class="master-section-heading"><h4>재료 정보</h4></div><div class="field-grid"><label class="field">표준재료명<input id="im-name" value="${escapeHtml(data.name)}"></label><label class="field">통계 집계명<select id="im-group">${state.codes.stat_groups.map(x=>`<option ${x===data.stat_group?'selected':''}>${x}</option>`).join('')}</select></label><label class="field">기본단위<select id="im-unit"><option value="">미지정</option>${state.codes.units.map(x=>`<option ${x===(data.default_unit||'')?'selected':''}>${x}</option>`).join('')}</select></label><label class="field">kg 환산계수(선택)<input id="im-factor" type="number" step="0.0001" value="${data.kg_factor??''}"></label></div><div class="recipe-options"><label><input id="im-excluded" type="checkbox" ${data.analysis_excluded?'checked':''}> 통계 분석 제외</label><label><input id="im-active" type="checkbox" ${data.active?'checked':''}> 사용</label></div>${id&&data.aliases?.length?`<div class="alias-list"><strong>별칭</strong><span>${data.aliases.map(x=>escapeHtml(x.alias)).join(' · ')}</span></div>`:''}${id?'<div class="master-menu-danger-row"><button type="button" class="danger-button" id="archive-ingredient">재료 삭제</button></div>':''}</section></div>`;
  const content=detailTab==='usage'?'<div id="master-ingredient-usage-root" class="master-ingredient-usage-root"><div class="master-ingredient-loading">사용 메뉴를 불러오는 중...</div></div>':info;
  panel.innerHTML=header+tabs+content;
  $$('[data-master-ingredient-detail]').forEach(button=>button.addEventListener('click',()=>{state.masterIngredientDetailTab=button.dataset.masterIngredientDetail;renderIngredientMasterPanel(id);if(button.dataset.masterIngredientDetail==='usage')loadIngredientUsage(id);}));
  const saveButton=$('#save-master-ingredient');
  if(saveButton)saveButton.addEventListener('click',async()=>{try{const body={name:$('#im-name').value,stat_group:$('#im-group').value,default_unit:$('#im-unit').value||null,kg_factor:$('#im-factor').value===''?null:Number($('#im-factor').value),analysis_excluded:$('#im-excluded').checked,active:$('#im-active').checked};const result=id?await api(`/api/master/ingredients/${id}`,json('PUT',body)):await api('/api/master/ingredients',json('POST',body));state.masterSelectionId=id||result.id;state.ingredientCache=[];toast('재료 기준정보를 저장했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
  $('#archive-ingredient')?.addEventListener('click',async()=>{if(!confirm('재료를 삭제(미사용 처리)할까요? 과거 식단 기록은 유지됩니다.'))return;try{await api(`/api/master/ingredients/${id}`,{method:'DELETE'});state.masterSelectionId=null;state.ingredientCache=[];toast('재료를 삭제 처리했습니다.');loadMaster();}catch(e){toast(e.message,true);}});
  if(id&&detailTab==='usage')loadIngredientUsage(id);
}

async function loadIngredientUsage(ingredientId,append=false){
  const usage=state.masterIngredientUsage;
  if(usage.loading)return;
  if(!append){usage.items=[];usage.offset=0;usage.total=0;usage.hasMore=false;usage.error='';}
  usage.ingredientId=ingredientId;usage.loading=true;const requestId=(usage.requestId||0)+1;usage.requestId=requestId;renderIngredientUsage();
  try{const params=new URLSearchParams({offset:String(usage.offset),limit:'20'});if(state.masterIngredientUsageQuery)params.set('q',state.masterIngredientUsageQuery);const data=await api(`/api/master/ingredients/${ingredientId}/usage-menus?${params}`);if(state.masterIngredientUsage!==usage||usage.requestId!==requestId)return;usage.items=append?usage.items.concat(data.items||[]):data.items||[];usage.offset=usage.items.length;usage.total=data.total||0;usage.hasMore=Boolean(data.has_more);}
  catch(e){if(state.masterIngredientUsage===usage){usage.error=e.message;}}
  usage.loading=false;renderIngredientUsage();
}
function renderIngredientUsage(){
  const root=$('#master-ingredient-usage-root'),usage=state.masterIngredientUsage;if(!root)return;
  if(usage.error){root.innerHTML=`<div class="master-history-error">사용 메뉴를 불러오지 못했습니다.<small>${escapeHtml(usage.error)}</small><button class="secondary-button" id="ingredient-usage-retry">다시 시도</button></div>`;$('#ingredient-usage-retry').addEventListener('click',()=>loadIngredientUsage(usage.ingredientId));return;}
  const toolbar=`<div class="ingredient-usage-toolbar"><strong>사용 메뉴 ${usage.total}개</strong><span class="search-submit-row"><input id="ingredient-usage-search" placeholder="메뉴 검색 후 Enter" value="${escapeHtml(state.masterIngredientUsageQuery)}"><button type="button" class="secondary-button" id="ingredient-usage-search-btn">조회</button></span></div>`;
  if(usage.loading&&!usage.items.length){root.innerHTML=toolbar+'<div class="master-ingredient-loading">사용 메뉴를 불러오는 중...</div>';bindIngredientUsageSearch();return;}
  if(!usage.items.length){root.innerHTML=toolbar+'<div class="master-history-empty">사용 메뉴가 없습니다.<small>현재 기준 레시피나 과거 식단에서 이 재료가 사용된 기록이 없습니다.</small></div>';bindIngredientUsageSearch();return;}
  root.innerHTML=toolbar+`<div class="ingredient-usage-list">${usage.items.map(item=>{const recent=item.has_historical_usage?`최근 ${item.last_used.date.replaceAll('-','.')} · ${escapeHtml({LUNCH:'중식',DINNER:'석식'}[item.last_used.meal_type]||item.last_used.meal_type)} · 실제 식수 ${item.last_used.actual_count==null?'-':`${numberText(item.last_used.actual_count)}명`} · ${item.historical_usage_count}회`:'최근 사용 없음';const badges=[item.menu_role,item.menu_canonical_name?`집계: ${item.menu_canonical_name}`:null].filter(Boolean);return `<article class="ingredient-usage-card"><div class="ingredient-usage-card-content"><div class="ingredient-usage-card-title"><strong>${escapeHtml(item.menu_name)}</strong><span class="ingredient-usage-badges">${badges.map(badge=>`<span>${escapeHtml(badge)}</span>`).join('')}</span></div><div class="ingredient-usage-card-meta">${recent}</div></div></article>`;}).join('')}</div>${usage.hasMore?'<button class="secondary-button master-history-more" id="ingredient-usage-more">더 보기</button>':''}`;
  bindIngredientUsageSearch();$('#ingredient-usage-more')?.addEventListener('click',()=>loadIngredientUsage(usage.ingredientId,true));
}
function bindIngredientUsageSearch(){bindSearchSubmit($('#ingredient-usage-search'),$('#ingredient-usage-search-btn'),value=>{state.masterIngredientUsageQuery=value.trim();loadIngredientUsage(state.masterIngredientUsage.ingredientId);});}
async function loadMoreMasterMenus(){ if(state.masterMenuHasMore && !state.masterMenuLoading){ state.masterMenuLoading=true; const PAGE=50; const q=state.masterMenuQuery; const offset=state.masterMenuOffset+PAGE; try{ const data=await api(`/api/master/menus?q=${encodeURIComponent(q)}&offset=${offset}&limit=${PAGE}`); if(state.masterMenuQuery!==q)return; const tbody=$('#master-content .master-list-wrap tbody'); if(!tbody)return; state.masterMenuOffset=offset; state.masterMenuHasMore=data.has_more; tbody.insertAdjacentHTML('beforeend', data.items.map(r=>`<tr data-menu-master='${r.id}' class='${r.id===state.masterSelectionId?'selected-row':''}'><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.role)}</td><td>${r.recipe_count}개</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')); }catch(e){ toast(e.message,true); } finally{ state.masterMenuLoading=false; } } } async function loadMoreMasterIngredients(){ if(state.masterIngredientHasMore && !state.masterIngredientLoading){ state.masterIngredientLoading=true; const PAGE=50; const q=state.masterIngredientQuery; const offset=state.masterIngredientOffset+PAGE; try{ const data=await api(`/api/master/ingredients?q=${encodeURIComponent(q)}&offset=${offset}&limit=${PAGE}`); if(state.masterIngredientQuery!==q)return; const tbody=$('#master-content .master-list-wrap tbody'); if(!tbody)return; state.masterIngredientOffset=offset; state.masterIngredientHasMore=data.has_more; tbody.insertAdjacentHTML('beforeend', data.items.map(r=>`<tr data-ingredient-master='${r.id}' class='${r.id===state.masterSelectionId?'selected-row':''}'><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.stat_group)}</td><td>${escapeHtml(r.default_unit||'')}</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')); }catch(e){ toast(e.message,true); } finally{ state.masterIngredientLoading=false; } } }

// ==================== 사용자 관리 ====================

function fmtDateTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return new Intl.DateTimeFormat('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }).format(d);
}

async function initUsers() {
  const root = $('#users-root');
  if (!root) return;
  root.innerHTML = '<div class="empty-editor">불러오는 중입니다.</div>';
  try {
    await loadUsersList('');
  } catch (e) {
    root.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}

async function loadUsersList(q) {
  const root = $('#users-root');
  if (!root) return;
  state.usersQuery = q || '';
  const data = await api(`/api/users?q=${encodeURIComponent(q)}`);
  const rows = data.items;
  root.innerHTML = `<div class="table-tools">
    <input id="users-search" placeholder="사용자 ID 또는 이름 입력 후 Enter 또는 조회" value="${escapeHtml(q)}">
    <button class="primary-button" id="users-search-btn">조회</button>
    <button class="secondary-button" id="new-user">＋ 사용자 등록</button>
  </div>
  <div class="table-wrap"><table class="data-table"><thead><tr>
    <th>사용자 ID</th><th>사용자명</th><th>권한</th><th>상태</th><th>최근 로그인</th><th>비밀번호 변경일</th><th>계정 생성일</th><th>작업</th>
  </tr></thead><tbody>${rows.map(r=>`<tr data-user-id="${r.id}">
    <td>${escapeHtml(r.username)}</td>
    <td>${escapeHtml(r.display_name)}</td>
    <td>${r.role==='admin'?'관리자':'일반사용자'}</td>
    <td>${r.active?'사용':'<span class="badge badge-warn">사용중지</span>'}</td>
    <td>${fmtDateTime(r.last_login_at)}</td>
    <td>${fmtDateTime(r.password_changed_at)}</td>
    <td>${fmtDateTime(r.created_at)}</td>
    <td class="user-actions-cell">
      <button class="ghost-button" data-act="edit" data-user-id="${r.id}">수정</button>
      <button class="ghost-button" data-act="reset" data-user-id="${r.id}">비밀번호 초기화</button>
      ${r.active?'<button class="ghost-button" data-act="deactivate" data-user-id="'+r.id+'">사용중지</button>':'<button class="ghost-button" data-act="activate" data-user-id="'+r.id+'">사용 재개</button>'}
    </td>
  </tr>`).join('')}</tbody></table></div>`;

  const si = $('#users-search', root);
  bindSearchSubmit(si, $('#users-search-btn', root), value => loadUsersList(value.trim()));
  $('#new-user', root).addEventListener('click', () => openUserCreateModal());
  $$('.user-actions-cell button', root).forEach(btn => btn.addEventListener('click', () => {
    const act = btn.dataset.act;
    const uid = Number(btn.dataset.userId);
    const user = rows.find(r => r.id === uid);
    if (act === 'edit') openUserEditModal(user);
    else if (act === 'reset') openResetPasswordModal(user);
    else if (act === 'deactivate') confirmDeactivate(user);
    else if (act === 'activate') confirmActivate(user);
  }));
}

function openUserCreateModal() {
  modal(`<h3>사용자 등록</h3>
  <form id="user-create-form" class="stack-form">
    <label>사용자 ID<input id="uc-username" required autocomplete="off"></label>
    <label>사용자명<input id="uc-display-name" autocomplete="off"></label>
    <label>권한<select id="uc-role"><option value="user">일반사용자</option><option value="admin">관리자</option></select></label>
    <label>초기 비밀번호<input id="uc-password" type="password" required autocomplete="new-password"></label>
    <label>초기 비밀번호 확인<input id="uc-password-confirm" type="password" required autocomplete="new-password"></label>
    <div class="form-hint">최소 8자 이상, 사용자 ID와 다른 비밀번호를 입력하세요.</div>
    <div id="uc-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><span></span><button type="submit" class="primary-button">등록</button></div>
  </form>`);
  $('#user-create-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#uc-error'); err.textContent = '';
    try {
      const body = {
        username: $('#uc-username').value,
        display_name: $('#uc-display-name').value,
        role: $('#uc-role').value,
        password: $('#uc-password').value,
        password_confirm: $('#uc-password-confirm').value,
      };
      await api('/api/users', json('POST', body));
      closeModal();
      toast('사용자가 등록되었습니다.');
      await loadUsersList(state.usersQuery || '');
    } catch (ex) { err.textContent = ex.message; }
  });
}

function openUserEditModal(user) {
  modal(`<h3>사용자 수정</h3>
  <form id="user-edit-form" class="stack-form">
    <label>사용자 ID<input value="${escapeHtml(user.username)}" disabled></label>
    <label>사용자명<input id="ue-display-name" value="${escapeHtml(user.display_name)}" autocomplete="off"></label>
    <label>권한<select id="ue-role"><option value="user" ${user.role==='user'?'selected':''}>일반사용자</option><option value="admin" ${user.role==='admin'?'selected':''}>관리자</option></select></label>
    <label>계정 상태<select id="ue-active"><option value="true" ${user.active?'selected':''}>사용</option><option value="false" ${!user.active?'selected':''}>사용중지</option></select></label>
    <div id="ue-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><span></span><button type="submit" class="primary-button">저장</button></div>
  </form>`);
  $('#user-edit-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#ue-error'); err.textContent = '';
    try {
      const body = {
        display_name: $('#ue-display-name').value,
        role: $('#ue-role').value,
        active: $('#ue-active').value === 'true',
      };
      await api(`/api/users/${user.id}`, json('PUT', body));
      closeModal();
      toast('사용자 정보가 수정되었습니다.');
      await loadUsersList(state.usersQuery || '');
    } catch (ex) { err.textContent = ex.message; }
  });
}

function openResetPasswordModal(user) {
  modal(`<h3>비밀번호 초기화</h3>
  <p class="modal-info">${escapeHtml(user.display_name)} (${escapeHtml(user.username)}) 사용자의 비밀번호를 초기화합니다.</p>
  <p class="modal-warn">초기화 후 사용자는 다음 로그인 시 새 비밀번호를 설정해야 합니다.</p>
  <form id="reset-pw-form" class="stack-form">
    <label>새 임시 비밀번호<input id="rp-password" type="password" required autocomplete="new-password"></label>
    <label>임시 비밀번호 확인<input id="rp-password-confirm" type="password" required autocomplete="new-password"></label>
    <div class="form-hint">최소 8자 이상, 사용자 ID와 다른 비밀번호를 입력하세요.</div>
    <div id="rp-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><button type="button" class="ghost-button" id="rp-cancel">취소</button><button type="submit" class="primary-button">비밀번호 초기화</button></div>
  </form>`);
  $('#rp-cancel').addEventListener('click', closeModal);
  $('#reset-pw-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#rp-error'); err.textContent = '';
    try {
      const body = {
        password: $('#rp-password').value,
        password_confirm: $('#rp-password-confirm').value,
      };
      await api(`/api/users/${user.id}/reset-password`, json('POST', body));
      closeModal();
      toast('비밀번호가 초기화되었습니다.');
      await loadUsersList(state.usersQuery || '');
    } catch (ex) { err.textContent = ex.message; }
  });
}

async function confirmDeactivate(user) {
  modal(`<h3>계정 사용중지</h3>
  <p>${escapeHtml(user.display_name)} (${escapeHtml(user.username)}) 사용자를 사용중지 하시겠습니까?</p>
  <p class="modal-warn">사용중지된 계정은 로그인할 수 없습니다. 기존 업무 기록은 유지됩니다.</p>
  <div class="save-bar"><button type="button" class="ghost-button" id="da-cancel">취소</button><button type="button" class="danger-button" id="da-confirm">사용중지</button></div>`);
  $('#da-cancel').addEventListener('click', closeModal);
  $('#da-confirm').addEventListener('click', async () => {
    try {
      await api(`/api/users/${user.id}`, json('PUT', { active: false }));
      closeModal();
      toast('사용자 계정이 사용중지되었습니다.');
      await loadUsersList(state.usersQuery || '');
    } catch (ex) { closeModal(); toast(ex.message, true); }
  });
}

async function confirmActivate(user) {
  try {
    await api(`/api/users/${user.id}`, json('PUT', { active: true }));
    toast('사용자 계정이 사용 재개되었습니다.');
    await loadUsersList(state.usersQuery || '');
  } catch (ex) { toast(ex.message, true); }
}

function openChangePasswordModal(forced) {
  modal(`<h3>${forced?'비밀번호 변경':'비밀번호 변경'}</h3>
  ${forced?'<p class="modal-warn">보안을 위해 비밀번호를 변경해야 합니다. 비밀번호를 변경하기 전에는 다른 업무 화면을 사용할 수 없습니다.</p>':''}
  <form id="change-pw-form" class="stack-form">
    <label>현재 비밀번호<input id="cp-current" type="password" required autocomplete="current-password"></label>
    <label>새 비밀번호<input id="cp-new" type="password" required autocomplete="new-password"></label>
    <label>새 비밀번호 확인<input id="cp-confirm" type="password" required autocomplete="new-password"></label>
    <div class="form-hint">최소 8자 이상, 사용자 ID와 다른 비밀번호를 입력하세요.</div>
    <div id="cp-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><span></span><button type="submit" class="primary-button">비밀번호 변경</button></div>
  </form>`);
  if (forced) {
    $('.modal-backdrop').removeEventListener('click', ()=>{});
    $('.modal-backdrop').addEventListener('click', e => { if (e.target.classList.contains('modal-backdrop')) { /* prevent close */ } });
  }
  $('#change-pw-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#cp-error'); err.textContent = '';
    try {
      const body = {
        current_password: $('#cp-current').value,
        new_password: $('#cp-new').value,
        new_password_confirm: $('#cp-confirm').value,
      };
      await api('/api/auth/change-password', json('POST', body));
      closeModal();
      toast('비밀번호가 변경되었습니다.');
      if (forced) {
        location.href = '/';
      }
    } catch (ex) { err.textContent = ex.message; }
  });
}

// ==================== 시스템 데이터 백업 ====================

function fmtFileSize(bytes) {
  if (!bytes) return '-';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
  return (bytes / 1073741824).toFixed(2) + ' GB';
}

async function initBackup() {
  await loadBackupList();
}

async function loadBackupList() {
  const root = $('#backup-root');
  if (!root) return;
  root.innerHTML = '<div class="empty-editor">불러오는 중입니다.</div>';
  try {
    const data = await api('/api/admin/backups');
    const rows = data.items;
    if (!rows.length) {
      root.innerHTML = '<div class="empty-editor">생성된 백업파일이 없습니다. 상단의 [지금 백업] 버튼을 눌러 백업을 생성하세요.</div>';
      return;
    }
    root.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr>
      <th>생성일시</th><th>구분</th><th>파일크기</th><th>상태</th><th>작업</th>
    </tr></thead><tbody>${rows.map(r=>`<tr data-backup-id="${r.id}">
      <td>${fmtDateTime(r.created_at)}</td>
      <td>${r.backup_type==='auto'?'자동':'수동'}</td>
      <td>${fmtFileSize(r.file_size)}</td>
      <td>${r.status==='completed'?'<span class="badge badge-ok">정상</span>':'<span class="badge badge-warn">오류</span>'}</td>
      <td>
        <button class="ghost-button" data-act="download" data-id="${r.id}">다운로드</button>
        ${r.backup_type==='manual'?`<button class="ghost-button" data-act="delete" data-id="${r.id}">삭제</button>`:''}
      </td>
    </tr>`).join('')}</tbody></table></div>`;
    $$('button[data-act]', root).forEach(btn => btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      const id = btn.dataset.id;
      if (act === 'download') downloadBackup(id);
      else if (act === 'delete') confirmDeleteBackup(id, btn.closest('tr'));
    }));
  } catch (e) {
    root.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}

async function createBackup() {
  const btn = $('#create-backup-btn');
  if (btn) { btn.disabled = true; btn.textContent = '백업 생성 중...'; }
  const lock = lockUI('시스템 데이터 백업을 만들고 있습니다.');
  try {
    await api('/api/admin/backups', { method: 'POST' });
    toast('시스템 데이터 백업이 생성되었습니다.');
    await loadBackupList();
  } catch (e) {
    toast(e.message, true);
  } finally {
    lock.release();
    if (btn) { btn.disabled = false; btn.textContent = '지금 백업'; }
  }
}

function downloadBackup(id) {
  window.location.href = `/api/admin/backups/${id}/download`;
  toast('다운로드를 시작했습니다. 중요한 백업파일은 PC 외의 별도 저장장치에도 보관하는 것을 권장합니다.');
}

async function confirmDeleteBackup(id, row) {
  modal(`<h3>백업파일 삭제</h3>
  <p>이 백업파일을 삭제하시겠습니까? 삭제 후 복구할 수 없습니다.</p>
  <div class="save-bar"><button type="button" class="ghost-button" id="bd-cancel">취소</button><button type="button" class="danger-button" id="bd-confirm">삭제</button></div>`);
  $('#bd-cancel').addEventListener('click', closeModal);
  $('#bd-confirm').addEventListener('click', async () => {
    try {
      await api(`/api/admin/backups/${id}`, { method: 'DELETE' });
      closeModal();
      toast('백업파일이 삭제되었습니다.');
      await loadBackupList();
    } catch (e) { closeModal(); toast(e.message, true); }
  });
}

// ==================== Excel 데이터 아카이브 ====================

async function initArchive() {
  await loadArchiveList();
}

async function loadArchiveList() {
  const root = $('#archive-root');
  if (!root) return;
  root.innerHTML = '<div class="empty-editor">불러오는 중입니다.</div>';
  try {
    const data = await api('/api/admin/archives');
    const rows = data.items;
    if (!rows.length) {
      root.innerHTML = '<div class="empty-editor">생성된 Excel 아카이브가 없습니다. 상단의 [Excel 아카이브 생성] 버튼을 눌러 생성하세요.</div>';
      return;
    }
    root.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr>
      <th>생성일시</th><th>조회기간</th><th>파일크기</th><th>상태</th><th>작업</th>
    </tr></thead><tbody>${rows.map(r=>`<tr data-archive-id="${r.id}">
      <td>${fmtDateTime(r.created_at)}</td>
      <td>${r.date_from && r.date_to ? r.date_from + ' ~ ' + r.date_to : '전체 데이터'}</td>
      <td>${fmtFileSize(r.file_size)}</td>
      <td>${r.status==='completed'?'<span class="badge badge-ok">다운로드 가능</span>':'<span class="badge badge-warn">만료</span>'}</td>
      <td>
        ${r.status==='completed'?`<button class="ghost-button" data-act="download" data-id="${r.id}">다운로드</button>`:''}
        <button class="ghost-button" data-act="delete" data-id="${r.id}">삭제</button>
      </td>
    </tr>`).join('')}</tbody></table></div>`;
    $$('button[data-act]', root).forEach(btn => btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      const id = btn.dataset.id;
      if (act === 'download') downloadArchive(id);
      else if (act === 'delete') confirmDeleteArchive(id);
    }));
  } catch (e) {
    root.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}

async function createArchive() {
  const btn = $('#create-archive-btn');
  const dateFrom = $('#archive-date-from')?.value || '';
  const dateTo = $('#archive-date-to')?.value || '';
  if (btn) { btn.disabled = true; btn.textContent = 'Excel 생성 중...'; }
  const lock = lockUI('Excel 데이터 아카이브를 만들고 있습니다.');
  try {
    let url = '/api/admin/archives';
    const params = [];
    if (dateFrom) params.push(`date_from=${dateFrom}`);
    if (dateTo) params.push(`date_to=${dateTo}`);
    if (params.length) url += '?' + params.join('&');
    const result = await api(url, { method: 'POST' });
    lock.release();
    toast('Excel 데이터 아카이브가 생성되었습니다.');
    await loadArchiveList();
    modal(`<h3>Excel 아카이브 생성 완료</h3>
    <p class="modal-info">파일명: ${escapeHtml(result.filename)}</p>
    <p class="modal-info">파일 크기: ${fmtFileSize(result.file_size)}</p>
    <p class="modal-warn">이 파일은 24시간 후 서버에서 자동 삭제됩니다. 미리 다운로드하여 보관하세요.</p>
    <div class="save-bar"><span></span><button type="button" class="primary-button" id="archive-download-now">다운로드</button></div>`);
    $('#archive-download-now').addEventListener('click', () => {
      closeModal();
      downloadArchive(result.id);
    });
  } catch (e) {
    toast(e.message, true);
  } finally {
    lock.release();
    if (btn) { btn.disabled = false; btn.textContent = 'Excel 아카이브 생성'; }
  }
}

function downloadArchive(id) {
  window.location.href = `/api/admin/archives/${id}/download`;
  toast('Excel 파일 다운로드를 시작했습니다.');
}

async function confirmDeleteArchive(id) {
  modal(`<h3>아카이브 삭제</h3>
  <p>이 Excel 아카이브 파일을 삭제하시겠습니까?</p>
  <div class="save-bar"><button type="button" class="ghost-button" id="ad-cancel">취소</button><button type="button" class="danger-button" id="ad-confirm">삭제</button></div>`);
  $('#ad-cancel').addEventListener('click', closeModal);
  $('#ad-confirm').addEventListener('click', async () => {
    try {
      await api(`/api/admin/archives/${id}`, { method: 'DELETE' });
      closeModal();
      toast('아카이브 파일이 삭제되었습니다.');
      await loadArchiveList();
    } catch (e) { closeModal(); toast(e.message, true); }
  });
}

// ==================== 발주 관리 ====================

const ORDER_STATUS_LABELS = { pending: '미처리', ordered: '발주완료', skipped: '발주안함' };

function orderRowKey(r) {
  return `${r.service_date}|${r.ingredient_id != null ? r.ingredient_id : 'n:' + r.ingredient_name}`;
}

function ordersUnitOptions(selected) {
  const units = state.codes?.units || ['kg','g','L','ml','개','봉','팩','판','통','캔','병','박스','단','묶음','장','줄','포','관','밧트'];
  return units.map(u => `<option ${u===selected?'selected':''}>${escapeHtml(u)}</option>`).join('');
}

function ordersStatusOptions(selected) {
  return Object.entries(ORDER_STATUS_LABELS).map(([value,label]) => `<option value="${value}" ${value===selected?'selected':''}>${label}</option>`).join('');
}

function ordersWeekdayLabel(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  return ['일','월','화','수','목','금','토'][d.getDay()];
}

function ordersMenuUsageLabel(r) {
  if (!r.menus || !r.menus.length) return '—';
  const names = r.menus.map(m => `${m.menu_name}(${m.meal_type_name || m.meal_type || ''})`);
  if (names.length <= 2) return names.join(', ');
  return `${names.slice(0, 2).join(', ')} 외 ${names.length - 2}개`;
}

function ordersMenuDetailHtml(r) {
  if (!r.menus || !r.menus.length) return '<span class="muted">식단에서 제외된 항목입니다.</span>';
  return r.menus.map(m => {
    const dateLabel = m.service_date ? `${m.service_date.slice(5).replace('-', '/')}(${ordersWeekdayLabel(m.service_date)})` : '';
    const mealLabel = m.meal_type_name || m.meal_type || '';
    return `<span class="order-menu-chip">${escapeHtml(dateLabel)} ${escapeHtml(mealLabel)} · ${escapeHtml(m.menu_name)} ${numberText(m.quantity)}${escapeHtml(m.unit || '')}</span>`;
  }).join('');
}

async function initOrders() {
  const from = $('#orders-date-from'), to = $('#orders-date-to');
  if (from && !from.value) {
    const start = mondayOf(new Date());
    from.value = isoDate(start);
    to.value = isoDate(addDays(start, 13));
  }
  await loadOrders();
}

async function loadOrders() {
  const root = $('#orders-root');
  if (!root) return;
  const from = $('#orders-date-from')?.value, to = $('#orders-date-to')?.value;
  if (!from || !to) { toast('조회기간을 지정해 주세요.', true); return; }
  root.innerHTML = '<div class="empty-editor">불러오는 중입니다.</div>';
  try {
    const data = await api(`/api/orders?start_date=${from}&end_date=${to}`);
    state.ordersItems = data.items;
    state.ordersSelection = new Set();
    state.ordersExpanded = new Set();
    $('#orders-period-label').textContent = `${compactPeriodLabel(data.start_date, data.end_date)} · 재료 ${data.items.length}건`;
    renderOrders();
  } catch (e) {
    root.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderOrders() {
  const root = $('#orders-root');
  if (!root) return;
  const view = state.ordersView || 'ingredient';
  const statusFilter = $('#orders-status-filter')?.value || '';
  const q = (state.ordersSearchQuery || '').trim().toLowerCase();
  let items = state.ordersItems.filter(r => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (q && !r.ingredient_name.toLowerCase().includes(q)) return false;
    return true;
  });
  if (view === 'ingredient') {
    items.sort((a, b) => a.ingredient_name.localeCompare(b.ingredient_name, 'ko') || a.service_date.localeCompare(b.service_date));
  } else {
    items.sort((a, b) => a.service_date.localeCompare(b.service_date) || a.ingredient_name.localeCompare(b.ingredient_name, 'ko'));
  }
  if (!items.length) {
    root.innerHTML = '<div class="empty-editor">조회기간에 발주 대상 재료가 없습니다.</div>';
    updateOrdersBulkBar();
    return;
  }
  let prevGroup = null;
  const bodyRows = items.map(r => {
    const key = orderRowKey(r);
    const group = view === 'ingredient' ? r.ingredient_name : r.service_date;
    const groupStart = group !== prevGroup;
    prevGroup = group;
    const groupClass = groupStart ? ' order-group-start' : '';
    const expanded = state.ordersExpanded.has(key);
    const groupBadge = r.order_group_id ? '<span class="badge badge-ok order-group-badge">묶음발주</span>' : '';
    const inPlanNote = r.in_plan ? '' : '<span class="badge badge-warn">식단 제외</span>';
    const detailInner = expanded ? ordersMenuDetailHtml(r) : '';
    return `<tr data-order-key="${key}" class="${groupClass}">
      <td class="col-check"><input type="checkbox" class="order-check" data-key="${key}" ${state.ordersSelection.has(key)?'checked':''}></td>
      <td class="order-ingredient-cell"><strong>${escapeHtml(r.ingredient_name)}</strong> ${groupBadge} ${inPlanNote}</td>
      <td class="order-required">${numberText(r.required_quantity)}${escapeHtml(r.required_unit || '')}</td>
      <td class="order-date-cell">${r.service_date.replaceAll('-', '.')}</td>
      <td class="order-menus-cell"><button type="button" class="link-button menu-usage-toggle" data-key="${key}">${escapeHtml(ordersMenuUsageLabel(r))} ${r.menus && r.menus.length ? '▾' : ''}</button></td>
      <td class="order-qty-cell"><input type="number" step="0.01" min="0" class="order-qty" value="${r.order_quantity ?? ''}"><select class="order-unit">${ordersUnitOptions(r.order_unit || r.required_unit || '')}</select></td>
      <td><input type="date" class="order-date" value="${r.order_date || ''}"></td>
      <td><input type="date" class="order-delivery" value="${r.delivery_date || ''}"></td>
      <td><select class="order-status">${ordersStatusOptions(r.status)}</select></td>
    </tr>
    <tr class="order-menu-detail ${expanded?'':'hidden'}" data-detail-key="${key}"><td colspan="9"><div class="order-menu-detail-inner">${detailInner}</div></td></tr>`;
  }).join('');
  root.innerHTML = `<div class="table-wrap orders-table-wrap"><table class="data-table orders-table"><thead><tr>
    <th class="col-check"><input type="checkbox" id="orders-check-all" ${items.length && items.every(r=>state.ordersSelection.has(orderRowKey(r)))?'checked':''}></th>
    <th>재료</th><th>필요량</th><th>사용일</th><th>사용 메뉴</th><th>발주량</th><th>발주일</th><th>배송일</th><th>상태</th>
  </tr></thead><tbody>${bodyRows}</tbody></table></div>`;
  bindOrdersTableEvents();
  updateOrdersBulkBar();
}

function bindOrdersTableEvents() {
  const root = $('#orders-root');
  if (!root) return;
  $('#orders-check-all')?.addEventListener('change', e => {
    $$('.order-check', root).forEach(cb => cb.checked = e.target.checked);
    syncOrdersSelection();
  });
  $$('.order-check', root).forEach(cb => cb.addEventListener('change', syncOrdersSelection));
  $$('.menu-usage-toggle', root).forEach(btn => btn.addEventListener('click', () => {
    const key = btn.dataset.key;
    const detail = $(`.order-menu-detail[data-detail-key="${key}"]`);
    if (detail) {
      const inner = $('.order-menu-detail-inner', detail);
      if (inner && !inner.dataset.rendered) {
        const item = state.ordersItems.find(r => orderRowKey(r) === key);
        if (item) inner.innerHTML = ordersMenuDetailHtml(item);
        if (inner) inner.dataset.rendered = '1';
      }
      detail.classList.toggle('hidden');
      if (state.ordersExpanded.has(key)) state.ordersExpanded.delete(key); else state.ordersExpanded.add(key);
    }
  }));
  $$('.order-qty', root).forEach(input => input.addEventListener('change', () => scheduleOrderSave(input.closest('tr'))));
  $$('.order-unit', root).forEach(sel => sel.addEventListener('change', () => scheduleOrderSave(sel.closest('tr'))));
  $$('.order-date', root).forEach(input => input.addEventListener('change', () => scheduleOrderSave(input.closest('tr'))));
  $$('.order-delivery', root).forEach(input => input.addEventListener('change', () => scheduleOrderSave(input.closest('tr'))));
  $$('.order-status', root).forEach(sel => sel.addEventListener('change', () => scheduleOrderSave(sel.closest('tr'))));
}

function syncOrdersSelection() {
  const sel = new Set();
  $$('.order-check:checked', $('#orders-root')).forEach(cb => sel.add(cb.dataset.key));
  state.ordersSelection = sel;
  updateOrdersBulkBar();
}

function updateOrdersBulkBar() {
  const bar = $('#orders-bulk-bar');
  if (!bar) return;
  const sel = state.ordersSelection;
  if (!sel.size) { bar.classList.add('hidden'); bar.innerHTML = ''; return; }
  const selectedItems = state.ordersItems.filter(r => sel.has(orderRowKey(r)));
  const names = new Set(selectedItems.map(r => r.ingredient_name));
  const sameIngredient = names.size === 1;
  const totalRequired = selectedItems.reduce((s, r) => s + (r.required_quantity || 0), 0);
  const unit = selectedItems[0]?.required_unit || '';
  const label = sameIngredient
    ? `${selectedItems[0].ingredient_name} ${selectedItems.length}건 선택 · 필요량 합계 ${numberText(totalRequired)}${escapeHtml(unit)}`
    : `${selectedItems.length}개 항목 선택`;
  bar.innerHTML = `<span class="orders-bulk-label">${escapeHtml(label)}</span>
    ${sameIngredient ? '<button class="primary-button" id="orders-group-btn">선택 항목 묶어 발주</button>' : ''}
    <button class="ghost-button" id="orders-bulk-date">발주일 변경</button>
    <button class="ghost-button" id="orders-bulk-delivery">배송일 변경</button>
    <button class="ghost-button" id="orders-bulk-ordered">발주 완료</button>
    <button class="ghost-button" id="orders-bulk-skipped">발주 안함</button>
    <button class="ghost-button" id="orders-bulk-clear">선택 해제</button>`;
  bar.classList.remove('hidden');
  $('#orders-group-btn')?.addEventListener('click', openGroupOrderModal);
  $('#orders-bulk-date')?.addEventListener('click', () => openBulkDateModal('order_date'));
  $('#orders-bulk-delivery')?.addEventListener('click', () => openBulkDateModal('delivery_date'));
  $('#orders-bulk-ordered')?.addEventListener('click', () => applyBulkStatus('ordered'));
  $('#orders-bulk-skipped')?.addEventListener('click', () => applyBulkStatus('skipped'));
  $('#orders-bulk-clear')?.addEventListener('click', () => {
    $$('.order-check', $('#orders-root')).forEach(cb => cb.checked = false);
    syncOrdersSelection();
  });
}

let _orderSaveTimer = null;
function scheduleOrderSave(tr) {
  clearTimeout(_orderSaveTimer);
  _orderSaveTimer = setTimeout(() => saveOrderRow(tr), 600);
}

function flashOrdersSaveState(message) {
  const el = $('#orders-save-state');
  if (!el) return;
  el.textContent = message;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.textContent = ''; }, 1800);
}

async function saveOrderRow(tr) {
  const key = tr.dataset.orderKey;
  const item = state.ordersItems.find(r => orderRowKey(r) === key);
  if (!item) return;
  const body = {
    service_date: item.service_date,
    ingredient_id: item.ingredient_id,
    ingredient_name: item.ingredient_name,
    required_quantity: item.required_quantity,
    required_unit: item.required_unit,
    order_quantity: $('.order-qty', tr).value === '' ? null : Number($('.order-qty', tr).value),
    order_unit: $('.order-unit', tr).value,
    order_date: $('.order-date', tr).value || null,
    delivery_date: $('.order-delivery', tr).value || null,
    status: $('.order-status', tr).value,
  };
  try {
    await api('/api/orders/items', json('PUT', { items: [body] }));
    item.order_quantity = body.order_quantity;
    item.order_unit = body.order_unit;
    item.order_date = body.order_date;
    item.delivery_date = body.delivery_date;
    item.status = body.status;
    flashOrdersSaveState('저장됨');
  } catch (e) {
    toast(e.message, true);
  }
}

function openGroupOrderModal() {
  const items = state.ordersItems.filter(r => state.ordersSelection.has(orderRowKey(r)));
  if (!items.length) return;
  const first = items[0];
  const dates = [...new Set(items.map(r => r.service_date))].sort();
  const totalRequired = items.reduce((s, r) => s + (r.required_quantity || 0), 0);
  const unit = first.required_unit || '';
  const orderDate = dates[0] ? isoDate(addDays(dates[0], -1)) : '';
  modal(`<div class="modal-head"><h3>${escapeHtml(first.ingredient_name)} 묶음 발주</h3><button class="icon-button" onclick="closeModal()">×</button></div>
  <div class="stack-form">
    <p class="modal-info">선택 사용분 ${items.length}건 · 사용기간 ${dates[0]} ~ ${dates[dates.length - 1]}</p>
    <p class="modal-info">필요량 합계 <strong>${numberText(totalRequired)}${escapeHtml(unit)}</strong></p>
    <label>발주량<input id="og-quantity" type="number" step="0.01" min="0" value="${totalRequired}"></label>
    <label>단위<select id="og-unit">${ordersUnitOptions(unit)}</select></label>
    <label>발주일<input id="og-order-date" type="date" value="${orderDate}"></label>
    <label>배송일<input id="og-delivery-date" type="date" value="${dates[0]}"></label>
    <div id="og-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><button type="button" class="ghost-button" id="og-cancel">취소</button><button type="button" class="primary-button" id="og-confirm">발주 완료</button></div>
  </div>`);
  $('#og-cancel').addEventListener('click', closeModal);
  $('#og-confirm').addEventListener('click', async () => {
    const err = $('#og-error'); err.textContent = '';
    try {
      await api('/api/orders/group', json('POST', {
        items: items.map(orderItemBody),
        order_quantity: $('#og-quantity').value === '' ? null : Number($('#og-quantity').value),
        order_unit: $('#og-unit').value,
        order_date: $('#og-order-date').value || null,
        delivery_date: $('#og-delivery-date').value || null,
      }));
      closeModal();
      toast(`${first.ingredient_name} 묶음 발주가 완료되었습니다.`);
      await loadOrders();
    } catch (e) { err.textContent = e.message; }
  });
}

function openBulkDateModal(field) {
  const items = state.ordersItems.filter(r => state.ordersSelection.has(orderRowKey(r)));
  if (!items.length) return;
  const label = field === 'order_date' ? '발주일' : '배송일';
  modal(`<div class="modal-head"><h3>${label} 일괄 변경</h3><button class="icon-button" onclick="closeModal()">×</button></div>
  <div class="stack-form">
    <p class="modal-info">선택한 ${items.length}개 항목의 ${label}을 일괄 변경합니다.</p>
    <label>${label}<input id="bd-date" type="date"></label>
    <div id="bd-error" class="form-error" aria-live="polite"></div>
    <div class="save-bar"><button type="button" class="ghost-button" id="bd-cancel">취소</button><button type="button" class="primary-button" id="bd-confirm">변경</button></div>
  </div>`);
  $('#bd-cancel').addEventListener('click', closeModal);
  $('#bd-confirm').addEventListener('click', async () => {
    const err = $('#bd-error'); err.textContent = '';
    const value = $('#bd-date').value;
    if (!value) { err.textContent = `${label}을 선택해 주세요.`; return; }
    try {
      await bulkUpdateOrders({ [field]: value });
      closeModal();
      toast(`${items.length}개 항목의 ${label}을 변경했습니다.`);
      await loadOrders();
    } catch (e) { err.textContent = e.message; }
  });
}

function orderItemBody(r) {
  return {
    service_date: r.service_date,
    ingredient_id: r.ingredient_id,
    ingredient_name: r.ingredient_name,
    required_quantity: r.required_quantity,
    required_unit: r.required_unit,
    order_quantity: r.order_quantity,
    order_unit: r.order_unit,
    order_date: r.order_date,
    delivery_date: r.delivery_date,
    status: r.status,
  };
}

async function bulkUpdateOrders(extra) {
  const items = state.ordersItems.filter(r => state.ordersSelection.has(orderRowKey(r)));
  const body = { items: items.map(orderItemBody), ...extra };
  return api('/api/orders/bulk', json('PUT', body));
}

function applyBulkStatus(status) {
  const items = state.ordersItems.filter(r => state.ordersSelection.has(orderRowKey(r)));
  if (!items.length) return;
  const label = ORDER_STATUS_LABELS[status];
  modal(`<div class="modal-head"><h3>${label} 처리</h3><button class="icon-button" onclick="closeModal()">×</button></div>
  <p class="modal-info">선택한 ${items.length}개 항목을 <strong>${label}</strong> 상태로 변경합니다.</p>
  <div class="save-bar"><button type="button" class="ghost-button" id="bs-cancel">취소</button><button type="button" class="primary-button" id="bs-confirm">${label}</button></div>`);
  $('#bs-cancel').addEventListener('click', closeModal);
  $('#bs-confirm').addEventListener('click', async () => {
    try {
      await bulkUpdateOrders({ status });
      closeModal();
      toast(`${items.length}개 항목을 ${label} 처리했습니다.`);
      await loadOrders();
    } catch (e) { closeModal(); toast(e.message, true); }
  });
}

/* ==================== 화면 잠금 (긴 작업 중 조작 차단) ==================== */
const UILock = { handles: [], el: null };
function uiLockElement(){
  if(UILock.el) return UILock.el;
  const el=document.createElement('div');
  el.id='ui-lock';el.className='ui-lock hidden';
  el.setAttribute('role','alertdialog');el.setAttribute('aria-modal','true');el.setAttribute('aria-live','assertive');
  el.innerHTML='<div class="ui-lock-box"><div class="ui-lock-spinner" aria-hidden="true"></div><strong class="ui-lock-message"></strong><div class="ui-lock-bar"><span></span></div><small class="ui-lock-percent"></small><p class="ui-lock-hint">작업이 끝날 때까지 기다려 주세요. 다른 화면으로 이동하거나 창을 닫지 마세요.</p></div>';
  ['click','mousedown','pointerdown','wheel','contextmenu'].forEach(type=>el.addEventListener(type,e=>{e.preventDefault();e.stopPropagation();},true));
  document.body.appendChild(el);UILock.el=el;return el;
}
function isUILocked(){ return UILock.handles.length>0; }
function renderUILock(){
  const el=uiLockElement();const top=UILock.handles[UILock.handles.length-1];
  const locked=!!top;
  el.classList.toggle('hidden',!locked);
  ['#app-shell','#modal-root','#analysis-drawer-root'].forEach(sel=>{const node=$(sel);if(node){if(locked)node.setAttribute('inert','');else node.removeAttribute('inert');}});
  document.body.classList.toggle('ui-locked',locked);
  if(!locked)return;
  $('.ui-lock-message',el).textContent=top.message;
  const determinate=typeof top.percent==='number';
  el.classList.toggle('determinate',determinate);
  $('.ui-lock-bar span',el).style.width=determinate?`${Math.max(2,Math.min(100,top.percent))}%`:'';
  $('.ui-lock-percent',el).textContent=determinate?`${Math.round(top.percent)}%`:'';
  if(document.activeElement && document.activeElement!==document.body) document.activeElement.blur();
}
function lockUI(message='처리하고 있습니다.', percent=null){
  const handle={message,percent:typeof percent==='number'?percent:null,released:false,
    update(nextMessage,nextPercent){if(handle.released)return;if(nextMessage)handle.message=nextMessage;handle.percent=typeof nextPercent==='number'?nextPercent:null;renderUILock();},
    release(){if(handle.released)return;handle.released=true;UILock.handles=UILock.handles.filter(h=>h!==handle);renderUILock();}};
  UILock.handles.push(handle);renderUILock();return handle;
}
async function withUILock(message, task){
  const lock=lockUI(message);
  try{ return await task(lock); }
  finally{ lock.release(); }
}
document.addEventListener('keydown',e=>{if(isUILocked()){e.preventDefault();e.stopPropagation();}},true);
window.addEventListener('beforeunload',e=>{if(isUILocked()){e.preventDefault();e.returnValue='';return '';}});

/* ==================== 식수 분석 ==================== */
const ANALYSIS_TABS = {daily:'날짜별 식수', popular:'인기 메뉴', menu:'메뉴별 식수', ingredient:'재료별 식수', weather:'날씨별 식수'};
const ANALYSIS_MIN_DAYS = {LUNCH:5, DINNER:4};
const ANALYSIS_MAIN_MENU_MIN_DAYS = {LUNCH:3, DINNER:2};
const ANALYSIS_SCOPES = {main_dish:'주찬만', main_menu:'메인 메뉴만', with_side:'부찬 포함', all:'전체'};
function analysisMinDefault(mealType, scope){ return (scope==='main_menu'?ANALYSIS_MAIN_MENU_MIN_DAYS:ANALYSIS_MIN_DAYS)[mealType]; }
const ANALYSIS_MENU_MODES = {name:'메뉴 이름', group:'통계집계명'};
const ANALYSIS_MAX_MENUS = 5;
const ANALYSIS_ING_MODES = {name:'재료 이름', group:'통계집계명(분석군)'};
// 메뉴별/재료별 탭의 비교 선택 설정
function analysisPicker(a){
  if(a.tab==='ingredient') return {modeKey:'ingMode', itemsKey:'ingItems', modes:ANALYSIS_ING_MODES, noun:'재료', served:'들어간 날',
    placeholder:{name:'재료 이름 입력 후 Enter 또는 검색 (예: 두부)', group:'통계집계명(분석군) 입력 후 Enter 또는 검색 (예: 돼지고기)'}, searchUrl:(mode,q)=>`/api/analysis/ingredient-keys/search?mode=${mode}&q=${encodeURIComponent(q)}`};
  return {modeKey:'menuMode', itemsKey:'menuItems', modes:ANALYSIS_MENU_MODES, noun:'메뉴', served:'나온 날',
    placeholder:{name:'정확한 메뉴 이름 입력 후 Enter 또는 검색 (예: LA갈비찜)', group:'통계집계명 입력 후 Enter 또는 검색 (예: 갈비찜)'}, searchUrl:(mode,q)=>`/api/analysis/menus/search?mode=${mode}&scope=${analysisState().menuScope}&q=${encodeURIComponent(q)}`};
}
const ANALYSIS_COLORS = ['#1d5f9a','#d9480f','#2b8a3e','#7048e8','#c2255c'];
const ANALYSIS_WEATHER_FILTERS = {all:'전체', rain:'비 오는 날', hot:'더운 날(28℃ 이상)', cold:'추운 날(영하)'};
function analysisDefaults(){
  const end=new Date();end.setHours(12,0,0,0);
  return {tab:'daily', start:isoDate(analysisMonthsBack(end,3)), end:isoDate(end), mealType:'LUNCH', showWeather:false, menuMode:'group', menuItems:[], menuScope:'main_dish', popScope:'main_dish', ingMode:'name', ingItems:[], popBasis:'name', popOrder:'top', popLimit:10, popMinDays:ANALYSIS_MIN_DAYS.LUNCH, weatherFilter:'all', result:null, query:null, band:null};
}
function analysisMonthsBack(end, months){ const d=new Date(end); d.setMonth(d.getMonth()-months); d.setDate(d.getDate()+1); return d; }
function analysisState(){ if(!state.analysis) state.analysis=analysisDefaults(); return state.analysis; }

function initAnalysis(){
  const a=analysisState();
  const tabs=$('#analysis-tabs');
  if(tabs && !tabs.dataset.bound){
    tabs.dataset.bound='1';
    $$('button[data-analysis-tab]',tabs).forEach(button=>button.addEventListener('click',()=>switchAnalysisTab(button.dataset.analysisTab)));
  }
  renderAnalysisConditions();
  renderAnalysisResult();
}

function switchAnalysisTab(tab){
  const a=analysisState();a.tab=tab;a.result=null;a.query=null;a.band=null;a.weatherFilter='all';
  $$('#analysis-tabs button[data-analysis-tab]').forEach(x=>x.classList.toggle('active',x.dataset.analysisTab===tab));
  renderAnalysisConditions();renderAnalysisResult();
}

function renderAnalysisConditions(){
  const a=analysisState();const root=$('#analysis-conditions');if(!root)return;
  const seg=(key,options,current)=>`<div class="an-seg">${options.map(([k,v])=>`<button type="button" data-${key}="${k}" class="${String(current)===String(k)?'active':''}">${v}</button>`).join('')}</div>`;
  const pk=(a.tab==='menu'||a.tab==='ingredient')?analysisPicker(a):null;
  const selector = pk
    ? `${a.tab==='menu'?`<div class="an-field"><span>메뉴 범위</span>${seg('menu-scope',Object.entries(ANALYSIS_SCOPES),a.menuScope)}</div>`:''}
       <div class="an-field"><span>조회 기준</span>${seg('pick-mode',Object.entries(pk.modes),a[pk.modeKey])}</div>
       <div class="an-field an-search-field"><span>${escapeHtml(pk.modes[a[pk.modeKey]])} (최대 ${ANALYSIS_MAX_MENUS}개 비교)</span><div class="an-search"><div class="search-submit-row"><input id="an-search-input" autocomplete="off" placeholder="${escapeHtml(pk.placeholder[a[pk.modeKey]])}"><button type="button" class="secondary-button" id="an-search-btn">검색</button></div><div class="an-search-list hidden" id="an-search-list"></div></div>
       <div class="an-chips" id="an-chips">${a[pk.itemsKey].map((name,i)=>`<span class="an-chip" style="--chip:${ANALYSIS_COLORS[i%ANALYSIS_COLORS.length]}">${escapeHtml(name)}<button type="button" data-remove-chip="${i}" aria-label="${escapeHtml(name)} 빼기">×</button></span>`).join('')||`<span class="muted">${pk.noun}를 검색한 뒤 목록에서 고르세요.</span>`}</div></div>`
    : a.tab==='popular'
    ? `<div class="an-field"><span>메뉴 범위</span>${seg('pop-scope',Object.entries(ANALYSIS_SCOPES),a.popScope)}</div>
       <div class="an-field"><span>기준</span>${seg('pop-basis',Object.entries(ANALYSIS_MENU_MODES),a.popBasis)}</div>
       <div class="an-field"><span>순서</span>${seg('pop-order',[['top','상위'],['bottom','하위']],a.popOrder)}</div>
       <div class="an-field"><span>개수</span>${seg('pop-limit',[[10,'10개'],[20,'20개']],a.popLimit)}</div>
       <label class="an-field"><span>최소 등장 횟수</span><input type="number" id="an-min-days" min="1" max="365" value="${a.popMinDays}" style="width:90px"></label>
`
    : '';
  const weatherFilter = (a.tab==='menu'||a.tab==='ingredient')
    ? `<label class="an-field"><span>날씨</span><select id="an-weather-filter">${Object.entries(ANALYSIS_WEATHER_FILTERS).map(([k,v])=>`<option value="${k}" ${a.weatherFilter===k?'selected':''}>${v}</option>`).join('')}</select></label>` : '';
  const weatherToggle = a.tab!=='weather'&&a.tab!=='popular'
    ? `<label class="an-check"><input type="checkbox" id="an-show-weather" ${a.showWeather?'checked':''}> 날씨 함께 보기</label>` : '';
  root.innerHTML=`<div class="an-row">
      <div class="an-field"><span>기간</span><div class="an-period"><input type="date" id="an-start" value="${a.start}"><span>~</span><input type="date" id="an-end" value="${a.end}"></div></div>
      <div class="an-field"><span>빠른 선택</span><div class="an-quick">${[1,3,6,12].map(m=>`<button type="button" class="ghost-button" data-months="${m}">${m}개월</button>`).join('')}</div></div>
      <div class="an-field"><span>배식</span><div class="an-seg">${[['LUNCH','중식'],['DINNER','석식']].map(([k,v])=>`<button type="button" data-meal="${k}" class="${a.mealType===k?'active':''}">${v}</button>`).join('')}</div></div>
    </div>
    <div class="an-row">${selector}${weatherFilter}${weatherToggle}<button type="button" class="primary-button an-query" id="an-query">조회</button></div>`;
  $('#an-start').addEventListener('change',e=>{a.start=e.target.value;});
  $('#an-end').addEventListener('change',e=>{a.end=e.target.value;});
  $$('[data-months]',root).forEach(b=>b.addEventListener('click',()=>{const end=new Date();end.setHours(12,0,0,0);a.end=isoDate(end);a.start=isoDate(analysisMonthsBack(end,Number(b.dataset.months)));$('#an-start').value=a.start;$('#an-end').value=a.end;}));
  $$('[data-meal]',root).forEach(b=>b.addEventListener('click',()=>{a.mealType=b.dataset.meal;a.popMinDays=analysisMinDefault(a.mealType,a.popScope);$$('[data-meal]',root).forEach(x=>x.classList.toggle('active',x===b));const md=$('#an-min-days');if(md)md.value=a.popMinDays;}));
  const segBind=(key,apply)=>$$(`[data-${key}]`,root).forEach(b=>b.addEventListener('click',()=>{apply(b.getAttribute(`data-${key}`));$$(`[data-${key}]`,root).forEach(x=>x.classList.toggle('active',x===b));}));
  segBind('pop-basis',v=>{a.popBasis=v;});segBind('pop-order',v=>{a.popOrder=v;});segBind('pop-limit',v=>{a.popLimit=Number(v);});
  if(pk) segBind('pick-mode',v=>{if(a[pk.modeKey]!==v){a[pk.modeKey]=v;a[pk.itemsKey]=[];renderAnalysisConditions();}});
  $('#an-min-days')?.addEventListener('change',e=>{a.popMinDays=Number(e.target.value)||analysisMinDefault(a.mealType,a.popScope);});
  segBind('pop-scope',v=>{a.popScope=v;a.popMinDays=analysisMinDefault(a.mealType,v);const md=$('#an-min-days');if(md)md.value=a.popMinDays;});
  segBind('menu-scope',v=>{a.menuScope=v;$('#an-search-list')?.classList.add('hidden');});
  $$('[data-remove-chip]',root).forEach(b=>b.addEventListener('click',()=>{a[pk.itemsKey].splice(Number(b.dataset.removeChip),1);renderAnalysisConditions();}));
  $('#an-weather-filter')?.addEventListener('change',e=>{a.weatherFilter=e.target.value;});
  $('#an-show-weather')?.addEventListener('change',e=>{a.showWeather=e.target.checked;if(a.result)renderAnalysisResult();});
  $('#an-query').addEventListener('click',runAnalysisQuery);
  if(a.tab==='menu'||a.tab==='ingredient') bindAnalysisSearch();
}

function bindAnalysisSearch(){
  const a=analysisState();const input=$('#an-search-input');const list=$('#an-search-list');if(!input||!list)return;
  const pk=analysisPicker(a);
  const search=async value=>{
    try{
      const data=await api(pk.searchUrl(a[pk.modeKey],value.trim()));
      list.innerHTML=data.items.length?`<div class="an-search-hint">${data.items.length}개 찾음 · 눌러서 추가</div>`+data.items.map((item,i)=>`<button type="button" data-index="${i}"><span>${escapeHtml(item.name)}</span><small>${numberText(item.served)}회 제공</small></button>`).join(''):`<div class="an-search-empty">찾는 이름이 없습니다.${a.tab==='menu'&&a.menuScope!=='all'?` 지금은 ‘${ANALYSIS_SCOPES[a.menuScope]}’ 범위에서 찾았어요. 메뉴 범위를 ‘전체’로 바꿔 보세요.`:''}</div>`;
      list.classList.remove('hidden');
      $$('button[data-index]',list).forEach(b=>b.addEventListener('mousedown',e=>{e.preventDefault();pick(data.items[Number(b.dataset.index)]);}));
    }catch(e){toast(e.message,true);}
  };
  const pick=item=>{
    if(!item)return;
    const items=a[pk.itemsKey];
    if(items.includes(item.name)){toast(`이미 고른 ${pk.noun}입니다.`);return;}
    if(items.length>=ANALYSIS_MAX_MENUS){toast(`${pk.noun}는 최대 ${ANALYSIS_MAX_MENUS}개까지 비교할 수 있습니다.`,true);return;}
    items.push(item.name);renderAnalysisConditions();
  };
  bindSearchSubmit(input,$('#an-search-btn'),search);
  input.addEventListener('keydown',e=>{ if(e.key==='Escape') list.classList.add('hidden'); });
  if(!document.body.dataset.anSearchOutside){
    document.body.dataset.anSearchOutside='1';
    document.addEventListener('mousedown',e=>{ const box=$('#an-search-list'); if(box && !e.target.closest('.an-search')) box.classList.add('hidden'); });
  }
}

function analysisQueryParams(){
  const a=analysisState();
  if(!a.start||!a.end) throw new Error('조회 기간을 선택해 주세요.');
  if(a.start>a.end) throw new Error('시작일이 종료일보다 늦습니다.');
  const params={start:a.start,end:a.end,meal_type:a.mealType};
  if(a.tab==='menu'){ if(!a.menuItems.length) throw new Error('목록에서 메뉴를 하나 이상 골라 주세요.'); params.mode=a.menuMode; params.names=[...a.menuItems]; params.weather=a.weatherFilter; params.scope=a.menuScope; }
  if(a.tab==='popular'){ const md=Number(a.popMinDays); if(!Number.isInteger(md)||md<1||md>365) throw new Error('최소 등장 횟수는 1~365 사이로 입력해 주세요.'); Object.assign(params,{basis:a.popBasis,order:a.popOrder,limit:a.popLimit,min_days:md,scope:a.popScope}); }
  if(a.tab==='ingredient'){ if(!a.ingItems.length) throw new Error('목록에서 재료를 하나 이상 골라 주세요.'); params.mode=a.ingMode; params.names=[...a.ingItems]; params.weather=a.weatherFilter; }
  return params;
}
function analysisSearchParams(params){ const sp=new URLSearchParams(); Object.entries(params).forEach(([k,v])=>{ if(Array.isArray(v)) v.forEach(x=>sp.append(k,x)); else sp.append(k,v); }); return sp; }
const ANALYSIS_ENDPOINTS={daily:'/api/analysis/daily',popular:'/api/analysis/popular-menus',menu:'/api/analysis/menus',ingredient:'/api/analysis/ingredients',weather:'/api/analysis/weather'};

async function runAnalysisQuery(){
  const a=analysisState();
  let params;
  try{ params=analysisQueryParams(); }catch(e){ toast(e.message,true); return; }
  const tab=a.tab;
  await withUILock(`${ANALYSIS_TABS[tab]}를 조회하고 있습니다.`, async()=>{
    try{
      const result=await api(`${ANALYSIS_ENDPOINTS[tab]}?${analysisSearchParams(params)}`);
      if(a.tab!==tab) return;
      a.result=result;a.query={tab,params};a.band=null;
      renderAnalysisResult();
    }catch(e){ toast(e.message,true); }
  });
}

function analysisDiffText(diff){ if(diff===null||diff===undefined) return '—'; if(diff>0) return `${numberText(diff)}명 많음`; if(diff<0) return `${numberText(-diff)}명 적음`; return '같음'; }
function analysisDiffClass(diff){ return diff>0?'an-more':diff<0?'an-less':''; }
function analysisWeatherIcon(w){ if(!w) return ''; if(w.is_rain) return (w.temp!==null&&w.temp<=1)?'🌨':'🌧'; return ''; }
function analysisTempClass(t){ if(t===null||t===undefined) return ''; if(t>=28) return 'an-hot'; if(t<0) return 'an-cold'; return ''; }
function analysisNum(v){ return v===null||v===undefined?'—':numberText(v); }

function renderAnalysisResult(){
  const a=analysisState();const root=$('#analysis-result');if(!root)return;
  if(!a.result){ root.innerHTML=`<div class="an-empty">조건을 정한 뒤 <strong>조회</strong> 버튼을 눌러 주세요.</div>`; return; }
  if(a.query.tab==='weather'){ renderAnalysisWeather(root,a.result); return; }
  if(a.query.tab==='popular'){ renderAnalysisPopular(root,a.result); return; }
  if(a.query.tab==='menu'||a.query.tab==='ingredient'){ renderAnalysisMenus(root,a.result); return; }
  const r=a.result;
  const titleBits=[r.meal_type_name, `${r.start} ~ ${r.end}`];
  if(r.menu_group) titleBits.unshift(`메뉴: ${r.menu_group}`);
  if(r.ingredient) titleBits.unshift(`재료: ${r.ingredient.name}`);
  if(r.weather_filter && r.weather_filter!=='all') titleBits.push(r.weather_filter_name);
  const note=r.low_sample_note?`<div class="an-note">${escapeHtml(r.low_sample_note)}</div>`:'';
  if(!r.points.length){ root.innerHTML=`<div class="an-card"><h3>${escapeHtml(titleBits.join(' · '))}</h3><div class="an-empty">조건에 맞는 식단(실제 식수 입력된 날)이 없습니다.</div></div>`; return; }
  const weatherNote=a.showWeather?`<p class="an-sub">날씨는 ${escapeHtml(r.meal_type_name)} 배식시간(${escapeHtml(r.weather_window)}) 관측값입니다. 기온은 평균, 비는 합계예요.</p>`:'';
  root.innerHTML=`<div class="an-card">
      <div class="an-card-head"><h3>${escapeHtml(titleBits.join(' · '))}</h3><span class="an-days">${numberText(r.points.length)}일</span></div>
      ${note}${weatherNote}
      <div class="an-legend"><span class="an-lg-actual"></span>실제 식수<span class="an-lg-usual"></span>평소 식수 (지난 1년 ${escapeHtml(r.meal_type_name)} 평균)</div>
      <div class="an-chart" id="an-chart"></div>
      <p class="an-sub">점이나 표의 날짜를 누르면 그날 식단을 볼 수 있어요.</p>
    </div>
    <div class="an-card">${analysisTableHtml(r.points,a.showWeather,true)}</div>`;
  drawAnalysisLineChart($('#an-chart'),r.points,{showWeather:a.showWeather,onClick:p=>openAnalysisDetail(p.date)});
  bindAnalysisTable(root);
}

function analysisTableHtml(points, showWeather, withDownload){
  return `<div class="an-table-head"><h4>날짜별 표</h4>${withDownload?'<button type="button" class="secondary-button" data-an-download>Excel 내려받기</button>':''}</div>
  <div class="table-wrap an-table-wrap"><table class="data-table an-table"><thead><tr><th>날짜</th><th class="num">실제</th><th class="num">평소</th><th class="num">차이(명)</th>${showWeather?'<th>배식시간 날씨</th>':''}</tr></thead><tbody>
  ${points.map(p=>`<tr data-an-date="${p.date}" tabindex="0"><td>${p.date} (${p.weekday})</td><td class="num">${numberText(p.actual)}명</td><td class="num">${p.usual===null?'—':numberText(p.usual)+'명'}</td><td class="num ${analysisDiffClass(p.diff)}">${analysisDiffText(p.diff)}</td>${showWeather?`<td>${p.weather?escapeHtml(p.weather.text):'<span class="muted">날씨 자료 없음</span>'}</td>`:''}</tr>`).join('')}
  </tbody></table></div>`;
}
function bindAnalysisTable(root){
  $$('tr[data-an-date]',root).forEach(tr=>{const open=()=>openAnalysisDetail(tr.dataset.anDate);tr.addEventListener('click',open);tr.addEventListener('keydown',e=>{if(e.key==='Enter')open();});});
  $$('[data-an-download]',root).forEach(b=>b.addEventListener('click',downloadAnalysisExcel));
}

async function downloadAnalysisExcel(){
  const a=analysisState();if(!a.query)return;
  const tabKey={daily:'daily',popular:'popular',menu:'menus',ingredient:'ingredients',weather:'weather'}[a.query.tab];
  await withUILock('Excel 파일을 만들고 있습니다.', async()=>{
    try{
      const response=await requestBinary(`/api/analysis/export.xlsx?${analysisSearchParams({...a.query.params,tab:tabKey})}`);
      const blob=await response.blob();
      triggerDownload(blob,parseContentDispositionFilename(response.headers.get('content-disposition'),'식수분석.xlsx'));
    }catch(e){toast(e.message,true);}
  });
}

function analysisNiceTicks(min,max,count=5){
  if(min===max){min-=10;max+=10;}
  const raw=(max-min)/count;const mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const step=[1,2,5,10].map(m=>m*mag).find(s=>s>=raw)||raw;
  const lo=Math.floor(min/step)*step, hi=Math.ceil(max/step)*step;
  const ticks=[];for(let v=lo;v<=hi+step/2;v+=step)ticks.push(Math.round(v));
  return {lo,hi,ticks};
}

function drawAnalysisLineChart(container, points, {showWeather=false, onClick}={}){
  if(!container)return;
  const width=Math.max(560,container.clientWidth||960), dense=points.length>1&&(width-76)/(points.length-1)<22;
  const top=showWeather?(dense?34:52):18, bottom=46, left=56, right=20, height=320+top;
  const values=points.flatMap(p=>[p.actual,p.usual]).filter(v=>v!==null&&v!==undefined);
  const pad=Math.max(5,(Math.max(...values)-Math.min(...values))*0.12);
  const {lo,hi,ticks}=analysisNiceTicks(Math.max(0,Math.min(...values)-pad),Math.max(...values)+pad);
  const plotW=width-left-right, plotH=height-top-bottom;
  const step=points.length>1?plotW/(points.length-1):0;
  const x=i=>points.length>1?left+i*step:left+plotW/2;
  const y=v=>top+plotH-(v-lo)/(hi-lo||1)*plotH;
  const path=(key)=>{let d='',open=false;points.forEach((p,i)=>{const v=p[key];if(v===null||v===undefined){open=false;return;}d+=`${open?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;open=true;});return d;};
  const labelEvery=Math.max(1,Math.ceil(points.length/Math.max(4,Math.floor(plotW/80))));
  const grid=ticks.map(t=>`<line x1="${left}" x2="${width-right}" y1="${y(t)}" y2="${y(t)}" class="an-grid"/><text x="${left-8}" y="${y(t)+4}" class="an-axis" text-anchor="end">${numberText(t)}</text>`).join('');
  let lastYear=null;
  const xLabels=points.map((p,i)=>{if(!(i%labelEvery===0||(i===points.length-1&&points.length<=12)))return '';const year=p.date.slice(0,4);const showYear=year!==lastYear;lastYear=year;
    return `<text x="${x(i)}" y="${height-bottom+18}" class="an-axis" text-anchor="middle">${escapeHtml(p.label.replace(/\(.\)$/,''))}</text>${showYear?`<text x="${x(i)}" y="${height-bottom+32}" class="an-axis an-axis-year" text-anchor="middle">${year}년</text>`:''}`;}).join('');
  const r=points.length>120?2:3.5;
  const dots=points.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.actual)}" r="${r}" class="an-dot-actual"/>${p.usual!==null&&p.usual!==undefined?`<circle cx="${x(i)}" cy="${y(p.usual)}" r="${Math.max(1.5,r-1)}" class="an-dot-usual"/>`:''}`).join('');
  let weatherMarks='';
  if(showWeather){
    weatherMarks=points.map((p,i)=>{const w=p.weather;if(!w)return '';const icon=analysisWeatherIcon(w);
      if(dense){return icon?`<text x="${x(i)}" y="${top-12}" text-anchor="middle" class="an-wicon-sm">${icon}</text>`:`<circle cx="${x(i)}" cy="${top-16}" r="2.2" class="an-tempdot ${analysisTempClass(w.temp)}"/>`;}
      return `<text x="${x(i)}" y="${top-30}" text-anchor="middle" class="an-wicon">${icon||'·'}</text><text x="${x(i)}" y="${top-12}" text-anchor="middle" class="an-wtemp ${analysisTempClass(w.temp)}">${w.temp===null?'':Math.round(w.temp)+'°'}</text>`;}).join('');
  }
  const hits=points.map((p,i)=>`<rect x="${x(i)-Math.max(step,8)/2}" y="${top}" width="${Math.max(step,8)}" height="${plotH}" class="an-hit" data-i="${i}"/>`).join('');
  container.innerHTML=`<svg class="an-svg" viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="실제 식수와 평소 식수 선그래프">
      ${grid}<line x1="${left}" x2="${width-right}" y1="${top+plotH}" y2="${top+plotH}" class="an-baseline"/>
      <text x="${left-44}" y="${top-4}" class="an-axis">(명)</text>
      <path d="${path('usual')}" class="an-line-usual"/><path d="${path('actual')}" class="an-line-actual"/>
      ${dots}${weatherMarks}<line class="an-cursor hidden" y1="${top}" y2="${top+plotH}"/>${xLabels}${hits}
    </svg><div class="an-tip hidden"></div>${showWeather&&dense?'<p class="an-sub">점이 많아 비 온 날만 🌧로 표시했어요(빨간 점은 28℃ 이상, 파란 점은 영하). 점에 마우스를 올리면 날씨가 보여요.</p>':''}`;
  const tip=$('.an-tip',container), cursor=$('.an-cursor',container), svg=$('svg',container);
  const show=(i,evt)=>{const p=points[i];if(!p)return;
    tip.innerHTML=`<strong>${escapeHtml(p.sentence)}</strong>${showWeather&&p.weather?`<span>${escapeHtml(p.weather.text)}</span>`:showWeather?'<span>날씨 자료 없음</span>':''}<em>눌러서 식단 보기</em>`;
    tip.classList.remove('hidden');
    const box=container.getBoundingClientRect();const scale=box.width/width;const px=x(i)*scale;
    tip.style.left=`${Math.min(Math.max(px,120),box.width-120)}px`;tip.style.top=`${Math.max(0,y(p.actual)*scale-12)}px`;
    cursor.setAttribute('x1',x(i));cursor.setAttribute('x2',x(i));cursor.classList.remove('hidden');};
  $$('.an-hit',svg).forEach(rect=>{const i=Number(rect.dataset.i);
    rect.addEventListener('mouseenter',e=>show(i,e));
    rect.addEventListener('mouseleave',()=>{tip.classList.add('hidden');cursor.classList.add('hidden');});
    rect.addEventListener('click',()=>onClick&&onClick(points[i]));});
}

function analysisSignedText(v){ if(v===null||v===undefined) return '—'; if(v>0) return `+${numberText(v)}명`; if(v<0) return `-${numberText(-v)}명`; return '0명'; }

function renderAnalysisPopular(root, r){
  const a=analysisState();
  const title=[`${r.order==='top'?'상위':'하위'} 인기 메뉴 ${r.limit}개`, r.scope_name, r.basis_name+' 기준', r.meal_type_name, `${r.start} ~ ${r.end}`];
  const explain=`그 메뉴가 나온 날 실제 식수가 평소 식수보다 평균 몇 명 많았는지(+), 적었는지(−)로 순서를 매겼어요. ${r.min_days}번보다 적게 나온 메뉴${r.excluded_too_few?` ${numberText(r.excluded_too_few)}개`:''}는 뺐어요.`;
  if(!r.items.length){ root.innerHTML=`<div class="an-card"><h3>${escapeHtml(title.join(' · '))}</h3><p class="an-sub">${escapeHtml(explain)}</p><div class="an-empty">${r.max_days?`가장 많이 나온 메뉴도 ${numberText(r.max_days)}번이에요. 최소 등장 횟수를 ${numberText(r.max_days)} 이하로 낮추거나 기간을 늘려 보세요.`:'이 기간에는 실제 식수가 입력된 날 중에 이 범위의 메뉴가 없어요. 기간이나 메뉴 범위를 바꿔 보세요.'}</div></div>`; return; }
  const maxAbs=Math.max(1,...r.items.map(i=>Math.abs(i.avg_diff||0)));
  const bars=r.items.map((item,i)=>{const v=item.avg_diff||0;const w=Math.abs(v)/maxAbs*50;
    return `<button type="button" class="an-pop-row" data-pop="${i}" title="${escapeHtml(item.name)} — 눌러서 메뉴별 식수 보기">
      <span class="an-pop-rank">${item.rank}</span><span class="an-pop-name">${escapeHtml(item.name)}</span>
      <span class="an-pop-track"><span class="an-pop-zero"></span><span class="an-pop-bar ${v>=0?'an-pop-pos':'an-pop-neg'}" style="${v>=0?`left:50%;width:${w}%`:`right:50%;width:${w}%`}"></span></span>
      <span class="an-pop-val ${analysisDiffClass(v)}">${analysisSignedText(item.avg_diff)}</span></button>`;}).join('');
  root.innerHTML=`<div class="an-card">
      <div class="an-card-head"><h3>${escapeHtml(title.join(' · '))}</h3><span class="an-days">후보 ${numberText(r.candidates)}개</span></div>
      <p class="an-explain">${escapeHtml(explain)}</p>
      <div class="an-pop-chart">${bars}</div>
      <p class="an-sub">막대나 표의 메뉴를 누르면 메뉴별 식수에서 그 메뉴를 날짜별로 볼 수 있어요.</p>
    </div>
    <div class="an-card"><div class="an-table-head"><h4>인기 메뉴 표</h4><button type="button" class="secondary-button" data-an-download>Excel 내려받기</button></div>
      <div class="table-wrap an-table-wrap"><table class="data-table an-table"><thead><tr><th class="num">순위</th><th>메뉴</th><th class="num">나온 날 수</th><th class="num">평균 실제</th><th class="num">평균 평소</th><th class="num">평균 차이(명)</th></tr></thead><tbody>
      ${r.items.map((item,i)=>`<tr data-pop="${i}" tabindex="0"><td class="num">${item.rank}</td><td>${escapeHtml(item.name)}</td><td class="num">${numberText(item.days)}일</td><td class="num">${analysisNum(item.avg_actual)}명</td><td class="num">${analysisNum(item.avg_usual)}명</td><td class="num ${analysisDiffClass(item.avg_diff)}">${analysisSignedText(item.avg_diff)}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  $$('[data-pop]',root).forEach(el=>{const go=()=>openPopularMenu(r.basis,r.items[Number(el.dataset.pop)].name,r.scope);el.addEventListener('click',go);el.addEventListener('keydown',e=>{if(e.key==='Enter')go();});});
  $$('[data-an-download]',root).forEach(b=>b.addEventListener('click',downloadAnalysisExcel));
}

function openPopularMenu(basis, name, scope='all'){
  const a=analysisState();
  switchAnalysisTab('menu');
  a.menuMode=basis;a.menuItems=[name];a.menuScope=scope;
  renderAnalysisConditions();
  runAnalysisQuery();
}

function renderAnalysisMenus(root, r){
  const a=analysisState();
  const isIng=a.query.tab==='ingredient';const noun=isIng?'재료':'메뉴';const served=isIng?'들어간 날':'나온 날';
  const color=i=>ANALYSIS_COLORS[i%ANALYSIS_COLORS.length];
  const title=[`${r.mode_name} 기준`, r.meal_type_name, `${r.start} ~ ${r.end}`];
  if(r.scope && r.scope!=='all') title.unshift(r.scope_name);
  if(r.weather_filter&&r.weather_filter!=='all') title.push(r.weather_filter_name);
  const notes=r.items.filter(i=>i.low_sample_note).map(i=>`<div class="an-note">${escapeHtml(i.name)}: ${escapeHtml(i.low_sample_note)}</div>`).join('');
  if(!r.dates.length){ root.innerHTML=`<div class="an-card"><h3>${escapeHtml(title.join(' · '))}</h3><div class="an-empty">조건에 맞는 식단(실제 식수 입력된 날)이 없습니다.</div></div>`; return; }
  const weatherNote=a.showWeather?`<p class="an-sub">날씨는 ${escapeHtml(r.meal_type_name)} 배식시간(${escapeHtml(r.weather_window)}) 관측값입니다. 기온은 평균, 비는 합계예요.</p>`:'';
  const legend=r.items.map((item,i)=>`<span class="an-lg-item"><span class="an-lg-swatch" style="background:${color(i)}"></span>${escapeHtml(item.name)}</span>`).join('')+`<span class="an-lg-item"><span class="an-lg-usual"></span>평소 식수 (지난 1년 ${escapeHtml(r.meal_type_name)} 평균)</span>`;
  const summary=`<table class="data-table an-table"><thead><tr><th>${noun}</th><th class="num">${served} 수</th><th class="num">평균 실제</th><th class="num">평균 평소</th><th class="num">평균 차이(명)</th></tr></thead><tbody>
    ${r.items.map((item,i)=>`<tr><td><span class="an-lg-swatch" style="background:${color(i)}"></span>${escapeHtml(item.name)}</td><td class="num">${numberText(item.days)}일</td><td class="num">${analysisNum(item.avg_actual)}${item.avg_actual===null?'':'명'}</td><td class="num">${analysisNum(item.avg_usual)}${item.avg_usual===null?'':'명'}</td><td class="num ${analysisDiffClass(item.avg_diff)}">${analysisSignedText(item.avg_diff)}</td></tr>`).join('')}</tbody></table>`;
  const rows=r.items.flatMap((item,i)=>item.points.map(p=>({item,i,p}))).sort((x,y)=>x.p.date.localeCompare(y.p.date)||x.i-y.i);
  const table=`<div class="table-wrap an-table-wrap"><table class="data-table an-table"><thead><tr><th>날짜</th><th>${noun}</th><th class="num">실제</th><th class="num">평소</th><th class="num">차이(명)</th>${a.showWeather?'<th>배식시간 날씨</th>':''}</tr></thead><tbody>
    ${rows.map(({item,i,p})=>`<tr data-an-date="${p.date}" tabindex="0"><td>${p.date} (${p.weekday})</td><td><span class="an-lg-swatch" style="background:${color(i)}"></span>${escapeHtml(item.name)}</td><td class="num">${numberText(p.actual)}명</td><td class="num">${p.usual===null?'—':numberText(p.usual)+'명'}</td><td class="num ${analysisDiffClass(p.diff)}">${analysisDiffText(p.diff)}</td>${a.showWeather?`<td>${p.weather?escapeHtml(p.weather.text):'<span class="muted">날씨 자료 없음</span>'}</td>`:''}</tr>`).join('')}
    </tbody></table></div>`;
  root.innerHTML=`<div class="an-card">
      <div class="an-card-head"><h3>${escapeHtml(title.join(' · '))}</h3><span class="an-days">${numberText(r.dates.length)}일</span></div>
      ${notes}${weatherNote}
      <div class="an-legend an-legend-multi">${legend}</div>
      <div class="an-chart" id="an-chart"></div>
      <p class="an-sub">${isIng?'재료가 들어간 날에만 점이 찍혀요. 날짜를 누르면 고른 재료가 들어간 메뉴를 표시해요.':'메뉴가 나온 날에만 점이 찍혀요.'} 점이나 표의 날짜를 누르면 그날 식단을 볼 수 있어요.</p>
    </div>
    <div class="an-card"><div class="an-table-head"><h4>${noun}별 요약</h4><button type="button" class="secondary-button" data-an-download>Excel 내려받기</button></div>${summary}</div>
    <div class="an-card"><div class="an-table-head"><h4>날짜별 표</h4></div>${table}</div>`;
  drawAnalysisMultiChart($('#an-chart'),r,{showWeather:a.showWeather,onClick:d=>openAnalysisDetail(d)});
  bindAnalysisTable(root);
}

function drawAnalysisMultiChart(container, r, {showWeather=false, onClick}={}){
  if(!container)return;
  const days=r.usual_line;const n=days.length;
  const idx=new Map(days.map((d,i)=>[d.date,i]));
  const series=r.items.map((item,si)=>({name:item.name,color:ANALYSIS_COLORS[si%ANALYSIS_COLORS.length],byDate:new Map(item.points.map(p=>[p.date,p]))}));
  const weatherByDate=new Map();r.items.forEach(item=>item.points.forEach(p=>{if(p.weather&&!weatherByDate.has(p.date))weatherByDate.set(p.date,p.weather);}));
  const width=Math.max(560,container.clientWidth||960), dense=n>1&&(width-76)/(n-1)<22;
  const top=showWeather?(dense?34:52):18, bottom=46, left=56, right=20, height=340+top;
  const values=[...days.map(d=>d.usual),...r.items.flatMap(i=>i.points.map(p=>p.actual))].filter(v=>v!==null&&v!==undefined);
  const pad=Math.max(5,(Math.max(...values)-Math.min(...values))*0.12);
  const {lo,hi,ticks}=analysisNiceTicks(Math.max(0,Math.min(...values)-pad),Math.max(...values)+pad);
  const plotW=width-left-right, plotH=height-top-bottom;
  const step=n>1?plotW/(n-1):0;
  const x=i=>n>1?left+i*step:left+plotW/2;
  const y=v=>top+plotH-(v-lo)/(hi-lo||1)*plotH;
  let usualPath='',open=false;days.forEach((d,i)=>{if(d.usual===null||d.usual===undefined){open=false;return;}usualPath+=`${open?'L':'M'}${x(i).toFixed(1)},${y(d.usual).toFixed(1)}`;open=true;});
  const r0=n>120?2.2:3.8;
  const lines=series.map(s=>{const pts=[...s.byDate.values()].sort((a,b)=>a.date.localeCompare(b.date));
    const d=pts.map((p,k)=>`${k?'L':'M'}${x(idx.get(p.date)).toFixed(1)},${y(p.actual).toFixed(1)}`).join('');
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.2"/>${pts.map(p=>`<circle cx="${x(idx.get(p.date))}" cy="${y(p.actual)}" r="${r0}" fill="${s.color}" stroke="#fff" stroke-width="1"/>`).join('')}`;}).join('');
  const labelEvery=Math.max(1,Math.ceil(n/Math.max(4,Math.floor(plotW/80))));
  const grid=ticks.map(t=>`<line x1="${left}" x2="${width-right}" y1="${y(t)}" y2="${y(t)}" class="an-grid"/><text x="${left-8}" y="${y(t)+4}" class="an-axis" text-anchor="end">${numberText(t)}</text>`).join('');
  let lastYear=null;
  const xLabels=days.map((d,i)=>{if(!(i%labelEvery===0||(i===n-1&&n<=12)))return '';const year=d.date.slice(0,4);const showYear=year!==lastYear;lastYear=year;
    return `<text x="${x(i)}" y="${height-bottom+18}" class="an-axis" text-anchor="middle">${escapeHtml(d.label.replace(/\(.\)$/,''))}</text>${showYear?`<text x="${x(i)}" y="${height-bottom+32}" class="an-axis an-axis-year" text-anchor="middle">${year}년</text>`:''}`;}).join('');
  let weatherMarks='';
  if(showWeather){
    weatherMarks=days.map((d,i)=>{const w=weatherByDate.get(d.date);if(!w)return '';const icon=analysisWeatherIcon(w);
      if(dense){return icon?`<text x="${x(i)}" y="${top-12}" text-anchor="middle" class="an-wicon-sm">${icon}</text>`:`<circle cx="${x(i)}" cy="${top-16}" r="2.2" class="an-tempdot ${analysisTempClass(w.temp)}"/>`;}
      return `<text x="${x(i)}" y="${top-30}" text-anchor="middle" class="an-wicon">${icon||'·'}</text><text x="${x(i)}" y="${top-12}" text-anchor="middle" class="an-wtemp ${analysisTempClass(w.temp)}">${w.temp===null?'':Math.round(w.temp)+'°'}</text>`;}).join('');
  }
  const hits=days.map((d,i)=>`<rect x="${x(i)-Math.max(step,8)/2}" y="${top}" width="${Math.max(step,8)}" height="${plotH}" class="an-hit" data-i="${i}"/>`).join('');
  container.innerHTML=`<svg class="an-svg" viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="실제 식수와 평소 식수 비교 선그래프">
      ${grid}<line x1="${left}" x2="${width-right}" y1="${top+plotH}" y2="${top+plotH}" class="an-baseline"/>
      <text x="${left-44}" y="${top-4}" class="an-axis">(명)</text>
      <path d="${usualPath}" class="an-line-usual"/>${lines}
      ${weatherMarks}<line class="an-cursor hidden" y1="${top}" y2="${top+plotH}"/>${xLabels}${hits}
    </svg><div class="an-tip hidden"></div>`;
  const tip=$('.an-tip',container), cursor=$('.an-cursor',container), svg=$('svg',container);
  const show=i=>{const d=days[i];if(!d)return;
    const served=series.filter(s=>s.byDate.has(d.date)).map(s=>{const p=s.byDate.get(d.date);return `<span><b style="color:${s.color}">●</b> ${escapeHtml(s.name)}: 실제 ${numberText(p.actual)}명 (${analysisDiffText(p.diff)})</span>`;}).join('');
    const w=weatherByDate.get(d.date);
    tip.innerHTML=`<strong>${escapeHtml(d.date)} ${escapeHtml(r.meal_type_name)} · 평소 ${d.usual===null?'—':numberText(d.usual)+'명'}</strong>${served}${showWeather?`<span>${w?escapeHtml(w.text):'날씨 자료 없음'}</span>`:''}<em>눌러서 식단 보기</em>`;
    tip.classList.remove('hidden');
    const box=container.getBoundingClientRect();const scale=box.width/width;const px=x(i)*scale;
    const ys=series.filter(s=>s.byDate.has(d.date)).map(s=>y(s.byDate.get(d.date).actual));
    tip.style.left=`${Math.min(Math.max(px,140),box.width-140)}px`;tip.style.top=`${Math.max(0,Math.min(...ys,y(d.usual??lo))*scale-12)}px`;
    cursor.setAttribute('x1',x(i));cursor.setAttribute('x2',x(i));cursor.classList.remove('hidden');};
  $$('.an-hit',svg).forEach(rect=>{const i=Number(rect.dataset.i);
    rect.addEventListener('mouseenter',()=>show(i));
    rect.addEventListener('mouseleave',()=>{tip.classList.add('hidden');cursor.classList.add('hidden');});
    rect.addEventListener('click',()=>onClick&&onClick(days[i].date));});
}

function renderAnalysisWeather(root, r){
  const a=analysisState();
  const section=(key,title,bands)=>{
    const maxAbs=Math.max(5,...bands.map(b=>Math.abs(b.avg_diff||0)));
    const bars=bands.map(b=>{const has=b.days>0&&b.avg_diff!==null;const pct=has?Math.abs(b.avg_diff)/maxAbs*50:0;
      return `<button type="button" class="an-bar-row ${a.band===`${key}:${b.key}`?'active':''}" data-band="${key}:${b.key}" ${b.days?'':'disabled'}>
        <span class="an-bar-label">${escapeHtml(b.label)}<small>${numberText(b.days)}일</small></span>
        <span class="an-bar-track"><span class="an-bar-zero"></span>${has?`<span class="an-bar ${b.avg_diff>=0?'pos':'neg'}" style="${b.avg_diff>=0?`left:50%;width:${pct}%`:`right:50%;width:${pct}%`}"></span>`:''}</span>
        <span class="an-bar-value ${analysisDiffClass(b.avg_diff)}">${has?(b.avg_diff===0?'평소와 같음':`평소보다 ${analysisDiffText(b.avg_diff)}`):'자료 없음'}</span></button>`;}).join('');
    const rows=bands.map(b=>`<tr data-band="${key}:${b.key}" class="${b.days?'':'an-row-empty'}"><td>${escapeHtml(b.label)}</td><td class="num">${numberText(b.days)}일</td><td class="num">${b.days?analysisNum(b.avg_actual)+'명':'—'}</td><td class="num">${b.days?analysisNum(b.avg_usual)+'명':'—'}</td><td class="num ${analysisDiffClass(b.avg_diff)}">${b.days?analysisDiffText(b.avg_diff):'—'}</td><td>${b.low_sample_note?`<span class="an-note-inline">${escapeHtml(b.low_sample_note)}</span>`:''}</td></tr>`).join('');
    return `<div class="an-card"><div class="an-card-head"><h3>${title}</h3></div>
      <div class="an-bars">${bars}</div>
      <div class="table-wrap"><table class="data-table an-table"><thead><tr><th>날씨</th><th class="num">일수</th><th class="num">평균 실제</th><th class="num">평균 평소</th><th class="num">평균 차이(명)</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  };
  const selected=a.band?[...r.rain.map(b=>({...b,group:'rain'})),...r.temperature.map(b=>({...b,group:'temp'}))].find(b=>`${b.group}:${b.key}`===a.band):null;
  root.innerHTML=`<div class="an-card an-card-plain"><div class="an-card-head"><h3>날씨별 식수 · ${escapeHtml(r.meal_type_name)} · ${escapeHtml(r.start)} ~ ${escapeHtml(r.end)}</h3><button type="button" class="secondary-button" data-an-download>Excel 내려받기</button></div>
      <p class="an-sub">${escapeHtml(r.meal_type_name)} 배식시간(${escapeHtml(r.weather_window)}) 날씨 기준입니다. 비는 그 시간 강수량 합계, 기온은 평균이에요. 날씨 자료와 평소 식수가 모두 있는 ${numberText(r.days)}일만 셉니다. 막대나 표를 누르면 해당 날짜가 보여요.</p></div>
    <div class="an-weather-grid">${section('rain','비 오는 날과 안 오는 날',r.rain)}${section('temp','기온별',r.temperature)}</div>
    <div id="an-band-dates">${selected?`<div class="an-card"><div class="an-card-head"><h3>${escapeHtml(selected.label)} · ${numberText(selected.days)}일</h3></div>${selected.low_sample_note?`<div class="an-note">${escapeHtml(selected.low_sample_note)}</div>`:''}${analysisTableHtml(selected.points,true,false)}</div>`:''}</div>`;
  $$('[data-band]',root).forEach(el=>el.addEventListener('click',()=>{a.band=el.dataset.band;renderAnalysisWeather(root,r);$('#an-band-dates')?.scrollIntoView({behavior:'smooth',block:'start'});}));
  bindAnalysisTable(root);
}

async function openAnalysisDetail(dateIso){
  const a=analysisState();if(!a.query)return;
  const mealType=a.query.params.meal_type;
  const ingNames=a.query.tab==='ingredient'?(a.query.params.names||[]):[];
  let root=$('#analysis-drawer-root');
  if(!root){root=document.createElement('div');root.id='analysis-drawer-root';document.body.appendChild(root);}
  root.innerHTML=`<div class="an-drawer-backdrop"><aside class="an-drawer" role="dialog" aria-modal="true" aria-label="식단 상세"><div class="an-drawer-head"><h3>식단 불러오는 중…</h3><button type="button" class="ghost-button" data-an-close>닫기</button></div><div class="an-drawer-body"><div class="empty-editor">불러오는 중입니다.</div></div></aside></div>`;
  const close=()=>{root.innerHTML='';document.removeEventListener('keydown',escClose);};
  const escClose=e=>{if(e.key==='Escape')close();};
  document.addEventListener('keydown',escClose);
  $('.an-drawer-backdrop',root).addEventListener('click',e=>{if(e.target.classList.contains('an-drawer-backdrop'))close();});
  $('[data-an-close]',root).addEventListener('click',close);
  try{
    const params=analysisSearchParams({date:dateIso,meal_type:mealType,...(ingNames.length?{ing_mode:a.query.params.mode,ing_names:ingNames}:{})});
    const d=await api(`/api/analysis/date-detail?${params}`);
    const ingredientName=ingNames.map(n=>`‘${n}’`).join(', ');
    $('.an-drawer-head h3',root).textContent=`${d.label} ${d.meal_type_name} 식단`;
    $('.an-drawer-body',root).innerHTML=`<div class="an-detail-figures">
        <div><span>실제</span><strong>${d.actual===null?'—':numberText(d.actual)+'명'}</strong></div>
        <div><span>평소</span><strong>${d.usual===null?'—':numberText(d.usual)+'명'}</strong></div>
        <div><span>차이</span><strong class="${analysisDiffClass(d.diff)}">${escapeHtml(d.diff_text)}</strong></div>
      </div>
      <p class="an-sub">평소 식수는 지난 1년 ${escapeHtml(d.meal_type_name)} ${numberText(d.usual_days)}일의 평균이에요.</p>
      <div class="an-detail-weather">${d.weather?`${analysisWeatherIcon(d.weather)} 배식시간 날씨: ${escapeHtml(d.weather.text)}`:`배식시간(${escapeHtml(d.weather_window)}) 날씨 자료가 없습니다.`}</div>
      ${ingredientName?`<div class="an-note">${a.query.params.mode==='group'?`고른 분석군(${escapeHtml(ingredientName)})에 속한 재료`:`고른 재료(${escapeHtml(ingredientName)})`}가 들어간 메뉴를 표시했어요.</div>`:''}
      <ol class="an-menu-list">${d.menus.map(m=>`<li class="${m.has_ingredient?'an-hl':''}">
        <details ${m.has_ingredient?'open':''}><summary><span class="an-menu-name">${escapeHtml(m.name)}</span>${m.is_main?'<span class="an-main-badge">★ 메인</span>':''}${m.has_ingredient?'<span class="an-ing-badge">재료 포함</span>':''}<small>${m.recipe_name?escapeHtml(m.recipe_name):'레시피 정보 없음'}</small></summary>
        ${m.ingredients.length?`<table class="data-table an-ing-table"><thead><tr><th>재료</th><th class="num">양</th></tr></thead><tbody>${m.ingredients.map(i=>`<tr class="${i.highlight?'an-hl-row':''}"><td>${escapeHtml(i.name)}</td><td class="num">${i.quantity===null||i.quantity===undefined?'<span class="muted">—</span>':`${numberText(i.quantity)} ${escapeHtml(i.unit||'')}`}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">등록된 재료가 없습니다.</p>'}
        </details></li>`).join('')}</ol>`;
  }catch(e){ $('.an-drawer-body',root).innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`; }
}

document.addEventListener('DOMContentLoaded',()=>init().catch(e=>toast(e.message,true)));
