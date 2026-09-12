const state = {
  view: 'workspace', mode: 'meal', focus: false, weeks: 2,
  weekStart: mondayOf(new Date()), workspace: null,
  selectedServiceId: null, selectedService: null, selectedMenuItemId: null,
  stats: null, dashboard: null, importToken: null, actualMealUpload: null, masterTab: 'menus', masterSelectionId: null, masterMenuDetailTab: 'recipe',
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
  if(ordersSearch){let composing=false;ordersSearch.addEventListener('compositionstart',()=>{composing=true;});ordersSearch.addEventListener('compositionend',e=>{composing=false;renderOrders();});ordersSearch.addEventListener('input',()=>{if(!composing)renderOrders();});}
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
  const titles={workspace:'',orders:'발주 관리',master:'메뉴·재료 기준정보',dashboard:'운영 대시보드','master-data':'기본 데이터 관리','stats-meals':'식수 통계','stats-menus':'메뉴 통계','stats-ingredients':'식재료 통계','stats-operations':'운영 기록 통계','users':'사용자 관리','backup':'시스템 데이터 백업','archive':'Excel 데이터 아카이브'};
  $('#page-title').textContent=titles[view]||'';
  $('#top-header').classList.toggle('hidden', view==='workspace');
  if(view==='orders') initOrders();
  if(view==='master') loadMaster();
  if(view==='master-data') loadMasterData();
  if(view==='dashboard') initDashboard();
  if(view==='stats-meals') initStatsPage('meals');
  if(view==='stats-menus') initStatsPage('menus');
  if(view==='stats-ingredients') initStatsPage('ingredients');
  if(view==='stats-operations') initStatsPage('operations');
  if(view==='users') initUsers();
  if(view==='backup') initBackup();
  if(view==='archive') initArchive();
  if(view==='dashboard'||view.startsWith('stats-')) expandStatsGroup();
  if(['master-data','users','backup','archive'].includes(view)) expandSettingsGroup();
}
function toggleNavGroup(e){
  const group=e.currentTarget.closest('.side-nav-group');
  if(!group)return;
  const collapsed=group.classList.toggle('collapsed');
  e.currentTarget.setAttribute('aria-expanded',String(!collapsed));
}
function expandStatsGroup(){ const group=$('.side-nav-group[data-group="stats"]'); if(group) group.classList.remove('collapsed'); }
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
        <div class="service-top"><span>${service.meal_type_name}</span><span>${service.service_time?service.service_time.slice(0,5):''}</span></div>
        ${service.concept_title?`<div class="service-concept">${escapeHtml(service.concept_title)}</div>`:''}
        <div class="service-meta">${statusMarkup(service)}${service.note?.trim()?'<span class="service-note-badge">특이사항</span>':''}</div>
        <div class="menu-lines">${service.menus.map(m=>`<div class="${m.is_representative?'representative-menu':''}">${m.is_representative?'<span class="representative-mark" title="대표 메뉴">★</span>':''}${escapeHtml(m.name)}</div>`).join('')||'<span class="muted">메뉴 없음</span>'}</div>
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
      </div>
    </section>
    <div class="panel-section meal-menu-section"><div class="panel-section-head"><h4>메뉴 ${service.menus.length}개</h4><button class="secondary-button" id="add-menu">＋ 메뉴 추가</button></div>
      <div class="menu-tabs" role="tablist">${service.menus.map(m=>`<button class="menu-tab ${m.id===selected?.id?'active':''}" data-menu-tab="${m.id}" role="tab" aria-selected="${m.id===selected?.id}">${escapeHtml(m.name)}</button>`).join('')}</div>
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
        <label class="representative-toggle"><input id="representative" type="checkbox" ${representative?'checked':''}><span>대표 메뉴</span></label>
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
    const current=state.selectedService?.menus.find(item=>item.id===menu.id);
    if(current)current.is_representative=event.target.checked;
    const boardService=state.workspace?.weeks.flatMap(week=>week.days).flatMap(day=>day.services).find(service=>service.id===state.selectedServiceId);
    const boardMenu=boardService?.menus.find(item=>item.id===menu.id);
    if(boardMenu)boardMenu.is_representative=event.target.checked;
    const draftMenu=state.mealEditorDraft?.menus[menu.id];
    if(draftMenu)draftMenu.isRepresentative=event.target.checked;
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
  if(menu)updateRecipeDiffStatus(menu);
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
  <div class="menu-picker-search"><label class="field">메뉴 검색<input id="picker-search" type="search" placeholder="메뉴명을 입력하세요" value="${escapeHtml(draft.query)}"></label><label class="field picker-role-filter">메뉴 역할<select id="picker-role"><option value="ALL">전체</option>${roles.map(r=>`<option value="${escapeHtml(r)}" ${r===draft.role?'selected':''}>${escapeHtml(r)}</option>`).join('')}</select></label><span id="picker-result-count" class="picker-result-count"></span></div>
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
  let debounceTimer;
  searchInput.addEventListener('input',()=>{draft.query=searchInput.value;clearTimeout(debounceTimer);debounceTimer=setTimeout(loadMenuPickerResults,250);});
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

/* ---------- 통계 공통 컴포넌트 (Phase 1) ---------- */
const PERIOD_PRESETS = {
  'this-month': { label: '이번 달' },
  '3m': { label: '최근 3개월' },
  '6m': { label: '최근 6개월' },
  '12m': { label: '최근 12개월' },
  'year': { label: '올해' },
  'custom': { label: '직접 선택' },
};
function periodRange(preset, ref=new Date()) {
  const end = new Date(ref); end.setHours(12,0,0,0);
  let start;
  if (preset === 'this-month') start = new Date(end.getFullYear(), end.getMonth(), 1);
  else if (preset === 'year') start = new Date(end.getFullYear(), 0, 1);
  else if (preset === 'custom') return null;
  else { const months = { '3m':3, '6m':6, '12m':12 }[preset] || 3; start = new Date(end.getFullYear(), end.getMonth()-months+1, 1); }
  return { start: isoDate(start), end: isoDate(end) };
}
function renderPeriodSelector(container, { preset='6m', onApply }) {
  container.innerHTML = `<div class="period-selector">
    <div class="period-presets">${Object.entries(PERIOD_PRESETS).map(([key,p])=>`<button type="button" class="period-preset${key===preset?' active':''}" data-preset="${key}">${p.label}</button>`).join('')}</div>
    <div class="period-custom${preset==='custom'?'':' hidden'}"><label>시작일 <input type="date" id="period-start"></label><label>종료일 <input type="date" id="period-end"></label><button type="button" class="primary-button" id="period-apply">조회</button></div>
  </div>`;
  const apply = (key) => {
    if (key === 'custom') { container.querySelector('.period-custom').classList.remove('hidden'); return; }
    container.querySelector('.period-custom').classList.add('hidden');
    $$('.period-preset', container).forEach(b=>b.classList.toggle('active', b.dataset.preset===key));
    const range = periodRange(key);
    if (range) onApply(range.start, range.end, key);
  };
  $$('.period-preset', container).forEach(b=>b.addEventListener('click', ()=>apply(b.dataset.preset)));
  $('#period-apply', container)?.addEventListener('click', ()=>{
    const start = $('#period-start', container).value, end = $('#period-end', container).value;
    if (!start || !end) { toast('기간을 입력해 주세요.', true); return; }
    onApply(start, end, 'custom');
  });
}
function kpiCard({label, value, sub='', hint='', tone=''}) {
  return `<div class="kpi-card${tone?` tone-${tone}`:''}"><span class="kpi-label">${label}</span><strong class="kpi-value">${value}</strong>${sub?`<span class="kpi-sub">${sub}</span>`:''}${hint?`<small class="kpi-hint">${hint}</small>`:''}</div>`;
}
function chartContainer({title, subtitle='', id='', actions='', body='', empty='데이터가 없습니다.'}) {
  return `<section class="chart-container"${id?` id="${id}"`:''}><header class="chart-head"><div><h3>${title}</h3>${subtitle?`<p>${subtitle}</p>`:''}</div>${actions?`<div class="chart-actions">${actions}</div>`:''}</header><div class="chart-body">${body||`<div class="stats-empty">${empty}</div>`}</div></section>`;
}
function openDetailDrawer({title, subtitle='', body='', footer=''}) {
  closeDetailDrawer();
  const backdrop = document.createElement('div');
  backdrop.className = 'detail-drawer-backdrop';
  backdrop.innerHTML = `<aside class="detail-drawer" role="dialog" aria-label="${escapeHtml(title)}">
    <header class="drawer-head"><div><h3>${escapeHtml(title)}</h3>${subtitle?`<small>${escapeHtml(subtitle)}</small>`:''}</div><button type="button" class="icon-button" id="drawer-close" aria-label="닫기">×</button></header>
    <div class="drawer-body">${body}</div>
    ${footer?`<footer class="drawer-foot">${footer}</footer>`:''}
  </aside>`;
  document.body.append(backdrop);
  backdrop.addEventListener('click', e=>{ if (e.target === backdrop) closeDetailDrawer(); });
  $('#drawer-close', backdrop).addEventListener('click', closeDetailDrawer);
  requestAnimationFrame(()=>backdrop.classList.add('open'));
}
function closeDetailDrawer() { $$('.detail-drawer-backdrop').forEach(x=>x.remove()); }
function downloadCsv(rows, cols, filename) {
  const header = cols.map(c=>`"${String(c.label).replace(/"/g,'""')}"`).join(',');
  const lines = rows.map(r=>cols.map(c=>{ const v = c.render ? c.render(r[c.key], r) : r[c.key]; return `"${String(v ?? '').replace(/"/g,'""')}"`; }).join(','));
  const csv = '\uFEFF' + [header, ...lines].join('\r\n');
  triggerDownload(new Blob([csv], {type:'text/csv;charset=utf-8;'}), `${filename}.csv`);
}
function renderStatisticsDataTable(container, {columns, rows, pageSize=10, filename='statistics'}) {
  const st = { q:'', sortKey:null, sortDir:1, page:0, pageSize, hidden:new Set() };
  const filtered = () => {
    let list = rows.slice();
    if (st.q) { const t = st.q.toLowerCase(); list = list.filter(r=>columns.some(c=>!st.hidden.has(c.key) && String(r[c.key] ?? '').toLowerCase().includes(t))); }
    if (st.sortKey) { const k = st.sortKey; list.sort((a,b)=>{ const av=a[k] ?? '', bv=b[k] ?? ''; const cmp = (typeof av==='number' && typeof bv==='number') ? av-bv : String(av).localeCompare(String(bv), 'ko'); return cmp * st.sortDir; }); }
    return list;
  };
  const updateTable = () => {
    const list = filtered();
    const pages = Math.max(1, Math.ceil(list.length / st.pageSize));
    st.page = Math.min(st.page, pages - 1);
    const slice = list.slice(st.page * st.pageSize, (st.page + 1) * st.pageSize);
    const visibleCols = columns.filter(c=>!st.hidden.has(c.key));
    const tableWrap = $('.stats-table-wrap', container);
    const footWrap = $('.stats-table-foot', container);
    if (tableWrap) tableWrap.innerHTML = `<table class="data-table stats-table"><thead><tr>${visibleCols.map(c=>`<th data-sort="${c.key}" class="${c.sortable===false?'':'sortable'}">${c.label}${st.sortKey===c.key?(st.sortDir>0?' ▲':' ▼'):''}</th>`).join('')}</tr></thead><tbody>${slice.length ? slice.map(r=>`<tr>${visibleCols.map(c=>`<td>${c.render ? c.render(r[c.key], r) : (r[c.key] ?? '-')}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${visibleCols.length}" class="stats-empty">데이터가 없습니다.</td></tr>`}</tbody></table>`;
    if (footWrap) footWrap.innerHTML = `<span>총 ${list.length}건</span><div class="stats-pager"><button type="button" class="ghost-button" id="stats-page-prev" ${st.page===0?'disabled':''}>‹</button><span>${st.page+1} / ${pages}</span><button type="button" class="ghost-button" id="stats-page-next" ${st.page>=pages-1?'disabled':''}>›</button></div>`;
    $('#stats-page-prev', container)?.addEventListener('click', ()=>{ st.page--; updateTable(); });
    $('#stats-page-next', container)?.addEventListener('click', ()=>{ st.page++; updateTable(); });
    $$('.stats-table th.sortable', container).forEach(th=>th.addEventListener('click', ()=>{
      const key = th.dataset.sort;
      if (st.sortKey === key) st.sortDir *= -1; else { st.sortKey = key; st.sortDir = 1; }
      st.page = 0; updateTable();
    }));
    st._lastList = list;
    st._lastVisibleCols = visibleCols;
  };
  const initRender = () => {
    const visibleCols = columns.filter(c=>!st.hidden.has(c.key));
    container.innerHTML = `<div class="stats-table-toolbar">
      <input type="search" id="stats-table-search" placeholder="검색" value="${escapeHtml(st.q)}">
      <div class="stats-table-actions">
        <div class="stats-columns-wrap"><button type="button" class="ghost-button" id="stats-table-cols-btn">열 선택</button><div class="stats-columns-pop hidden" id="stats-table-cols-pop">${columns.map(c=>`<label><input type="checkbox" data-col="${c.key}" ${st.hidden.has(c.key)?'':'checked'}> ${c.label}</label>`).join('')}</div></div>
        <select id="stats-table-size"><option value="10" ${st.pageSize===10?'selected':''}>10개</option><option value="25" ${st.pageSize===25?'selected':''}>25개</option><option value="50" ${st.pageSize===50?'selected':''}>50개</option></select>
        <button type="button" class="ghost-button" id="stats-table-csv">CSV 다운로드</button>
      </div>
    </div>
    <div class="stats-table-wrap"></div>
    <div class="stats-table-foot"></div>`;
    const si = $('#stats-table-search', container);
    let composing = false;
    si.addEventListener('compositionstart', () => { composing = true; });
    si.addEventListener('compositionend', e => { composing = false; st.q = e.target.value; st.page = 0; updateTable(); });
    si.addEventListener('input', e => { if (composing) return; st.q = e.target.value; st.page = 0; updateTable(); });
    $('#stats-table-csv', container).addEventListener('click', ()=>downloadCsv(st._lastList || filtered(), st._lastVisibleCols || columns.filter(c=>!st.hidden.has(c.key)), filename));
    $('#stats-table-size', container).addEventListener('change', e=>{ st.pageSize = Number(e.target.value); st.page = 0; updateTable(); });
    const colsBtn = $('#stats-table-cols-btn', container), colsPop = $('#stats-table-cols-pop', container);
    colsBtn.addEventListener('click', e=>{ e.stopPropagation(); colsPop.classList.toggle('hidden'); });
    $$('#stats-table-cols-pop input[type="checkbox"]', container).forEach(cb=>cb.addEventListener('change', ()=>{
      const key = cb.dataset.col;
      if (cb.checked) st.hidden.delete(key); else st.hidden.add(key);
      st.page = 0; updateTable();
    }));
    updateTable();
  };
  initRender();
}
async function initDashboard() {
  const root = $('#dashboard-root'); if (!root) return;
  root.innerHTML = `<div id="dashboard-period"></div><div class="stats-meal-type"><button type="button" data-meal="all" class="active">전체</button><button type="button" data-meal="lunch">중식</button><button type="button" data-meal="dinner">석식</button></div><div id="dashboard-content"><div class="empty-editor">불러오는 중입니다.</div></div>`;
  const periodRoot = $('#dashboard-period'), content = $('#dashboard-content');
  const current = { start: null, end: null, mealType: 'all' };
  const load = async () => {
    if (!current.start || !current.end) return;
    content.innerHTML = '<div class="empty-editor">통계를 계산하고 있습니다.</div>';
    try {
      const data = await api(`/api/statistics/dashboard?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`);
      renderDashboard(content, data, current);
    } catch (e) { content.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`; }
  };
  renderPeriodSelector(periodRoot, { preset: 'this-month', onApply: (start, end, preset) => { current.start = start; current.end = end; load(); } });
  $$('.stats-meal-type button', root).forEach(btn => btn.addEventListener('click', () => {
    current.mealType = btn.dataset.meal;
    $$('.stats-meal-type button', root).forEach(x => x.classList.toggle('active', x === btn));
    load();
  }));
  const range = periodRange('this-month');
  if (range) { current.start = range.start; current.end = range.end; load(); }
}
function renderDashboard(root, data, current) {
  const k = data.kpis;
  const tone = (rate) => rate === null ? '' : (Math.abs(rate) >= 15 ? 'danger' : (Math.abs(rate) >= 10 ? 'warn' : ''));
  const kpis = [
    kpiCard({ label: '운영일수', value: `${k.operating_days}일`, sub: `${data.start_date} ~ ${data.end_date}` }),
  ];
  if (current.mealType === 'all' || current.mealType === 'lunch') {
    const b = k.lunch;
    kpis.push(kpiCard({ label: '중식 실제 식수', value: b && b.actual_sum !== null ? `${numberText(b.actual_sum)}명` : '-', sub: b ? `계획 ${numberText(b.planned_sum)}명${b.deviation_rate !== null ? ` · ${b.deviation_rate > 0 ? '+' : ''}${b.deviation_rate}%` : ''}` : '', hint: b ? `입력률 ${b.input_rate ?? '-'}%` : '', tone: b ? tone(b.deviation_rate) : '' }));
  }
  if (current.mealType === 'all' || current.mealType === 'dinner') {
    const b = k.dinner;
    kpis.push(kpiCard({ label: '석식 실제 식수', value: b && b.actual_sum !== null ? `${numberText(b.actual_sum)}명` : '-', sub: b ? `계획 ${numberText(b.planned_sum)}명${b.deviation_rate !== null ? ` · ${b.deviation_rate > 0 ? '+' : ''}${b.deviation_rate}%` : ''}` : '', hint: b ? `입력률 ${b.input_rate ?? '-'}%` : '', tone: b ? tone(b.deviation_rate) : '' }));
  }
  kpis.push(kpiCard({ label: '사용 메뉴', value: `${k.unique_menu_count}종`, sub: '기간 내 고유 메뉴' }));
  const maxVal = Math.max(1, ...data.trend.map(m => Math.max(m.planned, m.actual)));
  const trendBars = data.trend.map(m => `<div class="trend-month"><div class="trend-bars"><div class="trend-bar planned" title="계획 ${numberText(m.planned)}명" style="height:${m.planned / maxVal * 100}%"></div><div class="trend-bar actual" title="실제 ${numberText(m.actual)}명" style="height:${m.actual / maxVal * 100}%"></div></div><span class="trend-label">${m.month.slice(5)}</span></div>`).join('');
  const trendHtml = `<div class="trend-chart">${trendBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div><div class="trend-legend"><span><i class="planned"></i>계획</span><span><i class="actual"></i>실제</span></div>`;
  const a = data.anomalies;
  const mealAnomalyHtml = a.meal.length ? a.meal.slice(0, 5).map(x => `<button type="button" class="anomaly-item" data-anomaly-type="meal" data-anomaly="${x.date}|${x.meal_type_name}"><div class="anomaly-top"><span class="anomaly-date">${x.date} ${x.meal_type_name}</span><span class="anomaly-badge level-${x.level === '중요' ? 'important' : 'check'}">${x.level}</span></div><div class="anomaly-meta">${x.type} · 계획 ${numberText(x.planned_count)}명 → 실제 ${numberText(x.actual_count)}명${x.deviation_rate !== null ? ` · 계획 대비 ${x.deviation_rate > 0 ? '+' : ''}${x.deviation_rate}%` : ''}</div></button>`).join('') : '<div class="stats-empty">식수 이상이 없습니다.</div>';
  const repeatHtml = a.menu_repeats.length ? a.menu_repeats.map(x => `<div class="anomaly-item static"><div class="anomaly-top"><span class="anomaly-date">${escapeHtml(x.menu_name)}</span><span class="anomaly-badge level-check">${x.type}</span></div><div class="anomaly-meta">${x.window_days}일 내 ${x.count}회 사용</div></div>`).join('') : '<div class="stats-empty">반복 메뉴가 없습니다.</div>';
  const ingHtml = a.ingredient_changes.length ? a.ingredient_changes.map(x => `<div class="anomaly-item static"><div class="anomaly-top"><span class="anomaly-date">${escapeHtml(x.group)}</span><span class="anomaly-badge level-${x.level === '중요' ? 'important' : 'check'}">${x.level}</span></div><div class="anomaly-meta">${x.current_kg}kg · 전월 대비 ${x.rate > 0 ? '+' : ''}${x.rate}%</div></div>`).join('') : '<div class="stats-empty">사용량 변화가 없습니다.</div>';
  const gapHtml = a.record_gaps.length ? a.record_gaps.slice(0, 5).map(x => `<div class="anomaly-item static"><div class="anomaly-top"><span class="anomaly-date">${x.date} ${x.meal_type_name}</span><span class="anomaly-badge level-important">누락</span></div><div class="anomaly-meta">${x.type}</div></div>`).join('') : '<div class="stats-empty">기록 누락이 없습니다.</div>';
  const menuMax = Math.max(1, ...data.menu_usage.map(x => x.count));
  const menuBars = data.menu_usage.map(x => `<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>${x.count}회</strong></div><div class="bar"><span style="width:${x.count / menuMax * 100}%"></span></div>`).join('');
  const repeatBars = data.repeated_menus.map(x => `<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>기간 ${x.period_count}회 · 이전 ${x.previous_4_weeks}회</strong></div>`).join('');
  const groupMax = Math.max(1, ...data.ingredient_groups.map(x => x.usage_rows));
  const groupBars = data.ingredient_groups.map(x => `<div class="stat-line"><span>${escapeHtml(x.group)}</span><strong>${x.usage_rows}건 · ${x.estimated_kg}kg</strong></div><div class="bar"><span style="width:${x.usage_rows / groupMax * 100}%"></span></div>`).join('');
  const workflowRows = [['조리지시서 출력', data.workflow.cooking_output], ['보존식 기록 완료', data.workflow.preservation_completed], ['실제 식수 입력', data.workflow.actual_recorded]].map(([label, count]) => `<div class="stat-line"><span>${label}</span><strong>${count}건</strong></div>`).join('');
  root.innerHTML = `
    <div class="kpi-grid">${kpis.join('')}</div>
    <div class="chart-grid">
      ${chartContainer({ title: '월별 계획 식수 / 실제 식수 추세', subtitle: '최근 12개월', body: trendHtml })}
      ${chartContainer({ title: '확인할 특이점', subtitle: '식수 이상 · 메뉴 반복 · 사용량 변화 · 기록 누락', body: `<div class="anomaly-groups"><div class="anomaly-group"><h4>식수 이상</h4>${mealAnomalyHtml}</div><div class="anomaly-group"><h4>메뉴 반복</h4>${repeatHtml}</div><div class="anomaly-group"><h4>사용량 변화</h4>${ingHtml}</div><div class="anomaly-group"><h4>기록 누락</h4>${gapHtml}</div></div>` })}
      ${chartContainer({ title: '메뉴 사용 현황', subtitle: 'TOP 5', body: `<div class="stat-list">${menuBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>`, actions: `<button type="button" class="link-button" id="dashboard-menu-detail">상세 보기</button>` })}
      ${chartContainer({ title: '최근 반복 메뉴', subtitle: '기간/직전 4주 사용 이력', body: `<div class="stat-list">${repeatBars || '<div class="stats-empty">반복 메뉴가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '식재료 사용 현황', subtitle: '주요 재료군', body: `<div class="stat-list">${groupBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '업무 기록 현황', subtitle: '완료 현황', body: `<div class="stat-list">${workflowRows}</div>` })}
    </div>`;
  $$('[data-anomaly-type="meal"]', root).forEach(btn => btn.addEventListener('click', () => {
    const [date, mealName] = btn.dataset.anomaly.split('|');
    openDetailDrawer({ title: '식수 이상 상세', subtitle: `${date} ${mealName}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: [
      { key: 'date', label: '날짜' },
      { key: 'meal_type_name', label: '구분' },
      { key: 'planned_count', label: '계획', render: v => numberText(v) },
      { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
      { key: 'deviation_rate', label: '편차율', render: v => v === null ? '계산 불가' : `${v > 0 ? '+' : ''}${v}%` },
      { key: 'usual_median', label: '평소 중앙값', render: v => v === null ? '비교 데이터 부족' : numberText(v) },
      { key: 'usual_deviation_rate', label: '평소 대비', render: (v, r) => r.usual_median === null ? '-' : `${v > 0 ? '+' : ''}${v}%` },
    ], rows: data.anomalies.meal.filter(x => x.date === date && x.meal_type_name === mealName), pageSize: 10, filename: 'dashboard_meal_anomaly' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  }));
  $('#dashboard-menu-detail', root)?.addEventListener('click', () => {
    openDetailDrawer({ title: '메뉴 사용 현황', subtitle: `${data.start_date} ~ ${data.end_date}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: [
      { key: 'menu_name', label: '메뉴명' },
      { key: 'count', label: '사용 횟수' },
    ], rows: data.menu_usage, pageSize: 10, filename: 'menu_usage' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  });
}
function initStatsPage(key) {
  if (key === 'meals') { initMealsStats(); return; }
  if (key === 'menus') { initMenusStats(); return; }
  if (key === 'ingredients') { initIngredientsStats(); return; }
  if (key === 'operations') { initOperationsStats(); return; }
}
async function initMealsStats() {
  const root = $('#stats-meals-root'); if (!root) return;
  root.innerHTML = `<div id="stats-meals-period"></div><div class="stats-meal-type"><button type="button" data-meal="all" class="active">전체</button><button type="button" data-meal="lunch">중식</button><button type="button" data-meal="dinner">석식</button></div><div id="stats-meals-content"><div class="empty-editor">불러오는 중입니다.</div></div>`;
  const periodRoot = $('#stats-meals-period'), content = $('#stats-meals-content');
  const current = { start: null, end: null, mealType: 'all' };
  const load = async () => {
    if (!current.start || !current.end) return;
    content.innerHTML = '<div class="empty-editor">통계를 계산하고 있습니다.</div>';
    try {
      const [data, trend] = await Promise.all([
        api(`/api/statistics/meals?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`),
        api(`/api/statistics/meals/trend?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`),
      ]);
      renderMealsStats(content, data, trend, current);
    } catch (e) { content.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`; }
  };
  renderPeriodSelector(periodRoot, { preset: '6m', onApply: (start, end, preset) => { current.start = start; current.end = end; load(); } });
  $$('.stats-meal-type button', root).forEach(btn => btn.addEventListener('click', () => {
    current.mealType = btn.dataset.meal;
    $$('.stats-meal-type button', root).forEach(x => x.classList.toggle('active', x === btn));
    load();
  }));
  const range = periodRange('6m');
  if (range) { current.start = range.start; current.end = range.end; load(); }
}
function renderMealsStats(root, data, trend, current) {
  const s = data.summary;
  const tone = (rate) => rate === null ? '' : (Math.abs(rate) >= 15 ? 'danger' : (Math.abs(rate) >= 10 ? 'warn' : ''));
  const kpis = [
    kpiCard({ label: '계획 식수 합계', value: `${numberText(s.planned_sum)}명`, sub: `운영일 ${s.service_count}일` }),
    kpiCard({ label: '실제 식수 합계', value: s.actual_sum === null ? '-' : `${numberText(s.actual_sum)}명`, sub: `입력 ${s.input_count}일`, hint: s.input_rate !== null ? `입력률 ${s.input_rate}%` : '입력 데이터 없음' }),
    kpiCard({ label: '계획 대비 차이', value: s.diff === null ? '-' : `${s.diff >= 0 ? '+' : ''}${numberText(s.diff)}명`, tone: tone(s.deviation_rate) }),
    kpiCard({ label: '계획 대비 편차율', value: s.deviation_rate !== null ? `${s.deviation_rate > 0 ? '+' : ''}${s.deviation_rate}%` : '계산 불가', tone: tone(s.deviation_rate) }),
  ];
  const breakdownHtml = current.mealType === 'all' ? `<div class="kpi-grid">${['lunch', 'dinner'].map(k => {
    const b = data.breakdown[k]; if (!b) return '';
    return kpiCard({ label: `${b.meal_type_name} 실제 식수`, value: b.actual_sum === null ? '-' : `${numberText(b.actual_sum)}명`, sub: `계획 ${numberText(b.planned_sum)}명${b.deviation_rate !== null ? ` · ${b.deviation_rate > 0 ? '+' : ''}${b.deviation_rate}%` : ' · 계산 불가'}`, hint: `입력률 ${b.input_rate ?? '-'}%`, tone: tone(b.deviation_rate) });
  }).join('')}</div>` : '';
  const maxVal = Math.max(1, ...trend.trend.map(m => Math.max(m.planned, m.actual)));
  const trendBars = trend.trend.map(m => `<div class="trend-month"><div class="trend-bars"><div class="trend-bar planned" title="계획 ${numberText(m.planned)}명" style="height:${m.planned / maxVal * 100}%"></div><div class="trend-bar actual" title="실제 ${numberText(m.actual)}명" style="height:${m.actual / maxVal * 100}%"></div></div><span class="trend-label">${m.month.slice(5)}</span></div>`).join('');
  const trendHtml = `<div class="trend-chart">${trendBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div><div class="trend-legend"><span><i class="planned"></i>계획</span><span><i class="actual"></i>실제</span></div>`;
  const wdMax = Math.max(1, ...data.weekday_averages.map(w => Math.max(w.planned_average || 0, w.actual_average || 0)));
  const wdBars = data.weekday_averages.map(w => `<div class="stat-line"><span>${w.weekday}</span><strong>${w.actual_average ?? '-'}명</strong></div><div class="bar"><span style="width:${(w.actual_average || 0) / wdMax * 100}%"></span></div><small class="muted">계획 평균 ${w.planned_average ?? '-'}명 · 입력 ${w.actual_records}/${w.records}일</small>`).join('');
  const devRows = data.backdata.filter(r => r.deviation_rate !== null).sort((a, b) => Math.abs(b.deviation_rate) - Math.abs(a.deviation_rate)).slice(0, 15);
  const devMax = Math.max(1, ...devRows.map(r => Math.abs(r.deviation_rate)));
  const devBars = devRows.map(r => `<div class="stat-line deviation-line"><span>${r.date.slice(5).replace('-', '/')} ${r.meal_type_name}</span><strong>${r.deviation_rate > 0 ? '+' : ''}${r.deviation_rate}%</strong></div><div class="deviation-bar ${r.deviation_rate >= 0 ? 'positive' : 'negative'}" style="width:${Math.abs(r.deviation_rate) / devMax * 100}%"></div>`).join('');
  const anomalyHtml = data.anomalies.length ? `<div class="anomaly-list">${data.anomalies.map(a => `<button type="button" class="anomaly-item" data-anomaly="${a.date}|${a.meal_type_name}"><div class="anomaly-top"><span class="anomaly-date">${a.date} ${a.meal_type_name}</span><span class="anomaly-badge level-${a.level === '중요' ? 'important' : 'check'}">${a.level}</span></div><div class="anomaly-meta">${a.type} · 계획 ${numberText(a.planned_count)}명 → 실제 ${numberText(a.actual_count)}명${a.deviation_rate !== null ? ` · 계획 대비 ${a.deviation_rate > 0 ? '+' : ''}${a.deviation_rate}%` : ''}${a.usual_median !== null ? ` · 평소 중앙값 ${numberText(a.usual_median)}명 (${a.usual_deviation_rate > 0 ? '+' : ''}${a.usual_deviation_rate}%)` : (a.insufficient_comparison ? ' · 비교 데이터 부족' : '')}</div></button>`).join('')}</div>` : '<div class="stats-empty">특이 일자가 없습니다.</div>';
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'diff', label: '차이', render: v => v === null ? '-' : `${v > 0 ? '+' : ''}${numberText(v)}` },
    { key: 'deviation_rate', label: '편차율', render: v => v === null ? '계산 불가' : `${v > 0 ? '+' : ''}${v}%` },
    { key: 'usual_median', label: '평소 중앙값', render: v => v === null ? '비교 데이터 부족' : numberText(v) },
    { key: 'usual_deviation_rate', label: '평소 대비', render: (v, r) => r.usual_median === null ? '-' : `${v > 0 ? '+' : ''}${v}%` },
    { key: 'input', label: '입력', render: v => v ? '✓' : '미입력' },
  ];
  root.innerHTML = `
    <div class="kpi-grid">${kpis.join('')}</div>
    ${breakdownHtml}
    <div class="chart-grid">
      ${chartContainer({ title: '월별 계획 식수 / 실제 식수 추세', subtitle: `${current.start} ~ ${current.end}`, body: trendHtml })}
      ${chartContainer({ title: '요일별 평균 식수', subtitle: '실제 식수 기준', body: `<div class="stat-list">${wdBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '계획 대비 편차 분포', subtitle: '특이값 강조', body: `<div class="stat-list deviation-list">${devBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '식수 특이 일자', subtitle: '계획/평소 대비 ±10% 이상', body: anomalyHtml, actions: `<button type="button" class="link-button" id="meals-backdata-btn">백데이터 보기</button>` })}
    </div>
    <div id="meals-backdata"></div>`;
  $$('.anomaly-item', root).forEach(btn => btn.addEventListener('click', () => {
    const [date, mealName] = btn.dataset.anomaly.split('|');
    openDetailDrawer({ title: '식수 특이 일자 상세', subtitle: `${date} ${mealName}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata.filter(r => r.date === date && r.meal_type_name === mealName), pageSize: 10, filename: 'meal_anomaly_backdata' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  }));
  $('#meals-backdata-btn', root)?.addEventListener('click', () => {
    openDetailDrawer({ title: '식수 백데이터', subtitle: `${current.start} ~ ${current.end}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: 'meal_backdata' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  });
}

async function initMenusStats() {
  const root = $('#stats-menus-root'); if (!root) return;
  root.innerHTML = `<div id="stats-menus-period"></div><div class="stats-meal-type"><button type="button" data-meal="all" class="active">전체</button><button type="button" data-meal="lunch">중식</button><button type="button" data-meal="dinner">석식</button></div><div class="stats-unused-days"><label>장기 미사용 기준 <select id="stats-unused-days"><option value="30">30일</option><option value="60">60일</option><option value="90" selected>90일</option><option value="180">180일</option></select></label></div><div id="stats-menus-content"><div class="empty-editor">불러오는 중입니다.</div></div>`;
  const periodRoot = $('#stats-menus-period'), content = $('#stats-menus-content');
  const current = { start: null, end: null, mealType: 'all', unusedDays: 90 };
  const load = async () => {
    if (!current.start || !current.end) return;
    content.innerHTML = '<div class="empty-editor">통계를 계산하고 있습니다.</div>';
    try {
      const data = await api(`/api/statistics/menus?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}&unused_days=${current.unusedDays}`);
      renderMenusStats(content, data, current);
    } catch (e) { content.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`; }
  };
  renderPeriodSelector(periodRoot, { preset: '6m', onApply: (start, end, preset) => { current.start = start; current.end = end; load(); } });
  $$('.stats-meal-type button', root).forEach(btn => btn.addEventListener('click', () => {
    current.mealType = btn.dataset.meal;
    $$('.stats-meal-type button', root).forEach(x => x.classList.toggle('active', x === btn));
    load();
  }));
  $('#stats-unused-days', root).addEventListener('change', e => { current.unusedDays = Number(e.target.value); load(); });
  const range = periodRange('6m');
  if (range) { current.start = range.start; current.end = range.end; load(); }
}
function renderMenusStats(root, data, current) {
  const s = data.summary;
  const kpis = [
    kpiCard({ label: '고유 메뉴 수', value: `${s.unique_menu_count}종`, sub: '기간 내 사용 메뉴' }),
    kpiCard({ label: '총 메뉴 사용 횟수', value: `${s.total_usage_count}회`, sub: '식단 내 메뉴 행 기준' }),
    kpiCard({ label: '신규 메뉴 수', value: `${s.new_menu_count}종`, sub: '기간 이전 사용 기록 없음' }),
    kpiCard({ label: '반복 메뉴 수', value: `${s.repeat_menu_count}종`, sub: '14일 2회 / 28일 3회' }),
    kpiCard({ label: '장기 미사용 메뉴', value: `${s.unused_menu_count}종`, sub: `${current.unusedDays}일 기준` }),
  ];
  const topMax = Math.max(1, ...data.top_menus.map(x => x.usage_count));
  const topBars = data.top_menus.map(x => {
    const clickable = x.menu_id !== null;
    return `<button type="button" class="menu-top-item" ${clickable ? `data-menu-id="${x.menu_id}"` : ''} data-menu-name="${escapeHtml(x.menu_name)}" ${clickable ? '' : 'disabled'}><div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>${x.usage_count}회</strong></div><div class="bar"><span style="width:${x.usage_count / topMax * 100}%"></span></div><small class="muted">중식 ${x.lunch_count}회 · 석식 ${x.dinner_count}회 · 최근 ${x.last_used}</small></button>`;
  }).join('');
  const repeatHtml = data.repeats.length ? data.repeats.map(x => `<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>${x.type} ${x.count}회</strong></div>`).join('') : '<div class="stats-empty">반복 메뉴가 없습니다.</div>';
  const unusedHtml = data.unused_menus.length ? data.unused_menus.slice(0, 10).map(x => `<div class="stat-line"><span>${escapeHtml(x.menu_name)}</span><strong>${x.days_since_last !== null ? `${x.days_since_last}일` : '사용 이력 없음'}</strong></div>`).join('') : '<div class="stats-empty">장기 미사용 메뉴가 없습니다.</div>';
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'role', label: '역할' },
    { key: 'menu_name', label: '메뉴명' },
    { key: 'menu_id', label: '메뉴 ID', render: v => v ?? '-' },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'previous_used_date', label: '이전 사용일', render: v => v ?? '-' },
    { key: 'days_since_previous', label: '경과일', render: v => v === null ? '-' : `${v}일` },
  ];
  root.innerHTML = `
    <div class="kpi-grid">${kpis.join('')}</div>
    <div class="chart-grid">
      ${chartContainer({ title: '메뉴 사용 TOP', subtitle: '클릭하면 상세 분석', body: `<div class="menu-top-list">${topBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '반복 메뉴', subtitle: '단기 14일 2회 · 과다 28일 3회', body: `<div class="stat-list">${repeatHtml}</div>` })}
      ${chartContainer({ title: '장기 미사용 메뉴', subtitle: `${current.unusedDays}일 기준`, body: `<div class="stat-list">${unusedHtml}</div>` })}
      ${chartContainer({ title: '백데이터', subtitle: '메뉴 사용 이력', body: '<div class="stats-empty">백데이터 보기 버튼으로 확인합니다.</div>', actions: `<button type="button" class="link-button" id="menus-backdata-btn">백데이터 보기</button>` })}
    </div>`;
  $$('.menu-top-item', root).forEach(btn => btn.addEventListener('click', () => {
    if (!btn.dataset.menuId) return;
    openMenuDetailDrawer(Number(btn.dataset.menuId), btn.dataset.menuName, current);
  }));
  $('#menus-backdata-btn', root)?.addEventListener('click', () => {
    openDetailDrawer({ title: '메뉴 백데이터', subtitle: `${current.start} ~ ${current.end}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: 'menu_backdata' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  });
}
async function openMenuDetailDrawer(menuId, menuName, current) {
  openDetailDrawer({ title: menuName, subtitle: `${current.start} ~ ${current.end}`, body: '<div class="empty-editor">불러오는 중입니다.</div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
  $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  try {
    const data = await api(`/api/statistics/menus/${menuId}?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`);
    renderMenuDetailDrawer(data);
  } catch (e) {
    const body = $('.drawer-body'); if (body) body.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}
function renderMenuDetailDrawer(data) {
  const s = data.summary;
  const body = $('.drawer-body'); if (!body) return;
  const monthlyMax = Math.max(1, ...data.monthly_usage.map(m => m.count));
  const monthlyBars = data.monthly_usage.map(m => `<div class="stat-line"><span>${m.month}</span><strong>${m.count}회</strong></div><div class="bar"><span style="width:${m.count / monthlyMax * 100}%"></span></div>`).join('');
  const historyHtml = data.recent_history.slice().reverse().map(r => `<div class="stat-line"><span>${r.date} ${r.meal_type_name}</span><strong>계획 ${numberText(r.planned_count)}명${r.actual_count !== null ? ` · 실제 ${numberText(r.actual_count)}명` : ''}</strong></div>`).join('');
  const coHtml = data.co_used.map(c => `<div class="stat-line"><span>${escapeHtml(c.menu_name)}</span><strong>${c.count}회</strong></div>`).join('');
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'role', label: '역할' },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'previous_used_date', label: '이전 사용일', render: v => v ?? '-' },
    { key: 'days_since_previous', label: '경과일', render: v => v === null ? '-' : `${v}일` },
  ];
  body.innerHTML = `
    <div class="kpi-grid">
      ${kpiCard({ label: '사용 횟수', value: `${s.usage_count}회`, sub: `중식 ${s.lunch_count}회 · 석식 ${s.dinner_count}회` })}
      ${kpiCard({ label: '최근 사용일', value: s.last_used ?? '-', sub: `최초 ${s.first_used ?? '-'}` })}
      ${kpiCard({ label: '평균 재사용 간격', value: s.avg_interval !== null ? `${s.avg_interval}일` : '-', sub: '연속 사용 간격 평균' })}
    </div>
    <div class="chart-grid">
      ${chartContainer({ title: '월별 사용 횟수', body: `<div class="stat-list">${monthlyBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '최근 사용 이력', body: `<div class="stat-list">${historyHtml || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '함께 사용된 메뉴', body: `<div class="stat-list">${coHtml || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '백데이터', body: '<div id="drawer-backdata"></div>' })}
    </div>`;
  renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: `menu_${data.menu_id}_backdata` });
}

async function initIngredientsStats() {
  const root = $('#stats-ingredients-root'); if (!root) return;
  root.innerHTML = `<div id="stats-ingredients-period"></div><div class="stats-meal-type"><button type="button" data-meal="all" class="active">전체</button><button type="button" data-meal="lunch">중식</button><button type="button" data-meal="dinner">석식</button></div><div class="stats-unused-days"><label>장기 미사용 기준 <select id="stats-ing-unused-days"><option value="30">30일</option><option value="60">60일</option><option value="90" selected>90일</option><option value="180">180일</option></select></label></div><div id="stats-ingredients-content"><div class="empty-editor">불러오는 중입니다.</div></div>`;
  const periodRoot = $('#stats-ingredients-period'), content = $('#stats-ingredients-content');
  const current = { start: null, end: null, mealType: 'all', unusedDays: 90 };
  const load = async () => {
    if (!current.start || !current.end) return;
    content.innerHTML = '<div class="empty-editor">통계를 계산하고 있습니다.</div>';
    try {
      const data = await api(`/api/statistics/ingredients?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}&unused_days=${current.unusedDays}`);
      renderIngredientsStats(content, data, current);
    } catch (e) { content.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`; }
  };
  renderPeriodSelector(periodRoot, { preset: '6m', onApply: (start, end, preset) => { current.start = start; current.end = end; load(); } });
  $$('.stats-meal-type button', root).forEach(btn => btn.addEventListener('click', () => {
    current.mealType = btn.dataset.meal;
    $$('.stats-meal-type button', root).forEach(x => x.classList.toggle('active', x === btn));
    load();
  }));
  $('#stats-ing-unused-days', root).addEventListener('change', e => { current.unusedDays = Number(e.target.value); load(); });
  const range = periodRange('6m');
  if (range) { current.start = range.start; current.end = range.end; load(); }
}
function renderIngredientsStats(root, data, current) {
  const s = data.summary;
  const kpis = [
    kpiCard({ label: '고유 재료 수', value: `${s.unique_ingredient_count}종`, sub: '기간 내 사용 재료' }),
    kpiCard({ label: '총 사용 횟수', value: `${s.total_usage_count}회`, sub: '식단 내 재료 행 기준' }),
    kpiCard({ label: '신규 재료 수', value: `${s.new_ingredient_count}종`, sub: '기간 이전 사용 기록 없음' }),
    kpiCard({ label: '장기 미사용 재료', value: `${s.unused_ingredient_count}종`, sub: `${current.unusedDays}일 기준` }),
  ];
  const topMax = Math.max(1, ...data.top_ingredients.map(x => x.usage_count));
  const topBars = data.top_ingredients.map(x => {
    const clickable = x.ingredient_id !== null;
    return `<button type="button" class="menu-top-item" ${clickable ? `data-ing-id="${x.ingredient_id}"` : ''} data-ing-name="${escapeHtml(x.ingredient_name)}" ${clickable ? '' : 'disabled'}><div class="stat-line"><span>${escapeHtml(x.ingredient_name)}</span><strong>${x.usage_count}회</strong></div><div class="bar"><span style="width:${x.usage_count / topMax * 100}%"></span></div><small class="muted">${x.quantity_g !== null ? `${(x.quantity_g / 1000).toFixed(1)}kg` : '-'} · 중식 ${x.lunch_count}회 · 석식 ${x.dinner_count}회 · 최근 ${x.last_used}</small></button>`;
  }).join('');
  const unusedHtml = data.unused_ingredients.length ? data.unused_ingredients.slice(0, 10).map(x => `<div class="stat-line"><span>${escapeHtml(x.ingredient_name)}</span><strong>${x.days_since_last !== null ? `${x.days_since_last}일` : '사용 이력 없음'}</strong></div>`).join('') : '<div class="stats-empty">장기 미사용 재료가 없습니다.</div>';
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'ingredient_name', label: '재료명' },
    { key: 'ingredient_id', label: '재료 ID', render: v => v ?? '-' },
    { key: 'quantity_g', label: '사용량(g)', render: v => v === null ? '-' : numberText(v) },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'previous_used_date', label: '이전 사용일', render: v => v ?? '-' },
    { key: 'days_since_previous', label: '경과일', render: v => v === null ? '-' : `${v}일` },
  ];
  root.innerHTML = `
    <div class="kpi-grid">${kpis.join('')}</div>
    <div class="chart-grid">
      ${chartContainer({ title: '재료 사용 TOP', subtitle: '클릭하면 상세 분석', body: `<div class="menu-top-list">${topBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '장기 미사용 재료', subtitle: `${current.unusedDays}일 기준`, body: `<div class="stat-list">${unusedHtml}</div>` })}
      ${chartContainer({ title: '백데이터', subtitle: '재료 사용 이력', body: '<div class="stats-empty">백데이터 보기 버튼으로 확인합니다.</div>', actions: `<button type="button" class="link-button" id="ingredients-backdata-btn">백데이터 보기</button>` })}
    </div>`;
  $$('.menu-top-item', root).forEach(btn => btn.addEventListener('click', () => {
    if (!btn.dataset.ingId) return;
    openIngredientDetailDrawer(Number(btn.dataset.ingId), btn.dataset.ingName, current);
  }));
  $('#ingredients-backdata-btn', root)?.addEventListener('click', () => {
    openDetailDrawer({ title: '재료 백데이터', subtitle: `${current.start} ~ ${current.end}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: 'ingredient_backdata' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  });
}
async function openIngredientDetailDrawer(ingredientId, ingredientName, current) {
  openDetailDrawer({ title: ingredientName, subtitle: `${current.start} ~ ${current.end}`, body: '<div class="empty-editor">불러오는 중입니다.</div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
  $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  try {
    const data = await api(`/api/statistics/ingredients/${ingredientId}?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`);
    renderIngredientDetailDrawer(data);
  } catch (e) {
    const body = $('.drawer-body'); if (body) body.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`;
  }
}
function renderIngredientDetailDrawer(data) {
  const s = data.summary;
  const body = $('.drawer-body'); if (!body) return;
  const monthlyMax = Math.max(1, ...data.monthly_usage.map(m => m.count));
  const monthlyBars = data.monthly_usage.map(m => `<div class="stat-line"><span>${m.month}</span><strong>${m.count}회</strong></div><div class="bar"><span style="width:${m.count / monthlyMax * 100}%"></span></div>`).join('');
  const historyHtml = data.recent_history.slice().reverse().map(r => `<div class="stat-line"><span>${r.date} ${r.meal_type_name}</span><strong>${escapeHtml(r.menu_name ?? '-')}${r.quantity_g !== null ? ` · ${(r.quantity_g / 1000).toFixed(1)}kg` : ''}${r.actual_count !== null ? ` · 실제 ${numberText(r.actual_count)}명` : ''}</strong></div>`).join('');
  const coHtml = data.co_used.map(c => `<div class="stat-line"><span>${escapeHtml(c.ingredient_name)}</span><strong>${c.count}회</strong></div>`).join('');
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'quantity_g', label: '사용량(g)', render: v => v === null ? '-' : numberText(v) },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'previous_used_date', label: '이전 사용일', render: v => v ?? '-' },
    { key: 'days_since_previous', label: '경과일', render: v => v === null ? '-' : `${v}일` },
  ];
  body.innerHTML = `
    <div class="kpi-grid">
      ${kpiCard({ label: '사용 횟수', value: `${s.usage_count}회`, sub: `중식 ${s.lunch_count}회 · 석식 ${s.dinner_count}회` })}
      ${kpiCard({ label: '총 사용량', value: `${(s.quantity_g / 1000).toFixed(1)}kg`, sub: `재료군 ${escapeHtml(data.stat_group)}` })}
      ${kpiCard({ label: '최근 사용일', value: s.last_used ?? '-', sub: `최초 ${s.first_used ?? '-'}` })}
      ${kpiCard({ label: '평균 재사용 간격', value: s.avg_interval !== null ? `${s.avg_interval}일` : '-', sub: '연속 사용 간격 평균' })}
    </div>
    <div class="chart-grid">
      ${chartContainer({ title: '월별 사용 횟수', body: `<div class="stat-list">${monthlyBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '최근 사용 이력', body: `<div class="stat-list">${historyHtml || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '함께 사용된 재료', body: `<div class="stat-list">${coHtml || '<div class="stats-empty">데이터가 없습니다.</div>'}</div>` })}
      ${chartContainer({ title: '백데이터', body: '<div id="drawer-backdata"></div>' })}
    </div>`;
  renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: `ingredient_${data.ingredient_id}_backdata` });
}

async function initOperationsStats() {
  const root = $('#stats-operations-root'); if (!root) return;
  root.innerHTML = `<div id="stats-operations-period"></div><div class="stats-meal-type"><button type="button" data-meal="all" class="active">전체</button><button type="button" data-meal="lunch">중식</button><button type="button" data-meal="dinner">석식</button></div><div id="stats-operations-content"><div class="empty-editor">불러오는 중입니다.</div></div>`;
  const periodRoot = $('#stats-operations-period'), content = $('#stats-operations-content');
  const current = { start: null, end: null, mealType: 'all' };
  const load = async () => {
    if (!current.start || !current.end) return;
    content.innerHTML = '<div class="empty-editor">통계를 계산하고 있습니다.</div>';
    try {
      const data = await api(`/api/statistics/operations?start_date=${current.start}&end_date=${current.end}&meal_type=${current.mealType}`);
      renderOperationsStats(content, data, current);
    } catch (e) { content.innerHTML = `<div class="form-error">${escapeHtml(e.message)}</div>`; }
  };
  renderPeriodSelector(periodRoot, { preset: '6m', onApply: (start, end, preset) => { current.start = start; current.end = end; load(); } });
  $$('.stats-meal-type button', root).forEach(btn => btn.addEventListener('click', () => {
    current.mealType = btn.dataset.meal;
    $$('.stats-meal-type button', root).forEach(x => x.classList.toggle('active', x === btn));
    load();
  }));
  const range = periodRange('6m');
  if (range) { current.start = range.start; current.end = range.end; load(); }
}
function renderOperationsStats(root, data, current) {
  const s = data.summary;
  const rateTone = (rate) => rate === null ? '' : (rate < 70 ? 'danger' : (rate < 90 ? 'warn' : ''));
  const kpis = [
    kpiCard({ label: '운영 배식 건수', value: `${s.service_count}건`, sub: `${current.start} ~ ${current.end}` }),
    kpiCard({ label: '실제 식수 입력률', value: s.actual_input_rate !== null ? `${s.actual_input_rate}%` : '-', sub: `입력 ${s.actual_input_count}건`, tone: rateTone(s.actual_input_rate) }),
    kpiCard({ label: '보존식 기록 완료율', value: s.preservation_rate !== null ? `${s.preservation_rate}%` : '-', sub: `완료 ${s.preservation_count}건`, tone: rateTone(s.preservation_rate) }),
    kpiCard({ label: '식단표 출력률', value: s.meal_plan_output_rate !== null ? `${s.meal_plan_output_rate}%` : '-', sub: `출력 ${s.meal_plan_output_count}건`, tone: rateTone(s.meal_plan_output_rate) }),
    kpiCard({ label: '조리지시서 출력률', value: s.cooking_output_rate !== null ? `${s.cooking_output_rate}%` : '-', sub: `출력 ${s.cooking_output_count}건`, tone: rateTone(s.cooking_output_rate) }),
  ];
  const breakdownHtml = current.mealType === 'all' ? `<div class="kpi-grid">${['lunch', 'dinner'].map(k => {
    const b = data.breakdown[k]; if (!b) return '';
    return kpiCard({ label: `${b.meal_type_name} 완료율`, value: `${b.actual_input_rate ?? '-'}%`, sub: `식수 입력 ${b.actual_input_count}/${b.service_count}건`, hint: `보존식 ${b.preservation_rate ?? '-'}% · 식단표 ${b.meal_plan_output_rate ?? '-'}% · 조리지시서 ${b.cooking_output_rate ?? '-'}%`, tone: rateTone(b.actual_input_rate) });
  }).join('')}</div>` : '';
  const trendMax = Math.max(1, ...data.trend.map(m => Math.max(m.actual_input_rate || 0, m.preservation_rate || 0, m.meal_plan_output_rate || 0, m.cooking_output_rate || 0)));
  const trendBars = data.trend.map(m => `<div class="trend-month"><div class="trend-bars"><div class="trend-bar actual" title="식수 입력 ${m.actual_input_rate ?? '-'}%" style="height:${(m.actual_input_rate || 0) / trendMax * 100}%"></div><div class="trend-bar preservation" title="보존식 ${m.preservation_rate ?? '-'}%" style="height:${(m.preservation_rate || 0) / trendMax * 100}%"></div><div class="trend-bar meal-plan" title="식단표 ${m.meal_plan_output_rate ?? '-'}%" style="height:${(m.meal_plan_output_rate || 0) / trendMax * 100}%"></div><div class="trend-bar cooking" title="조리지시서 ${m.cooking_output_rate ?? '-'}%" style="height:${(m.cooking_output_rate || 0) / trendMax * 100}%"></div></div><span class="trend-label">${m.month.slice(5)}</span></div>`).join('');
  const trendHtml = `<div class="trend-chart">${trendBars || '<div class="stats-empty">데이터가 없습니다.</div>'}</div><div class="trend-legend"><span><i class="actual"></i>식수 입력</span><span><i class="preservation"></i>보존식</span><span><i class="meal-plan"></i>식단표</span><span><i class="cooking"></i>조리지시서</span></div>`;
  const gaps = data.anomalies.record_gaps;
  const gapGroups = {};
  gaps.forEach(g => { gapGroups[g.type] = (gapGroups[g.type] || 0) + 1; });
  const gapHtml = Object.entries(gapGroups).length ? Object.entries(gapGroups).map(([type, count]) => `<div class="stat-line"><span>${type}</span><strong>${count}건</strong></div>`).join('') : '<div class="stats-empty">기록 누락이 없습니다.</div>';
  const lateHtml = data.anomalies.late_inputs.length ? data.anomalies.late_inputs.slice(0, 10).map(x => `<div class="stat-line"><span>${x.date} ${x.meal_type_name}</span><strong>${x.actual_count}명 · 입력 ${x.recorded_at ? x.recorded_at.slice(0, 10) : '-'}</strong></div>`).join('') : '<div class="stats-empty">지연 입력이 없습니다.</div>';
  const p = data.preservation;
  const managerHtml = p.by_manager.length ? p.by_manager.map(m => `<div class="stat-line"><span>${escapeHtml(m.manager_name)}</span><strong>${m.count}건</strong></div>`).join('') : '<div class="stats-empty">보존식 기록이 없습니다.</div>';
  const tempHtml = p.temperature_records.length ? p.temperature_records.slice(0, 10).map(t => `<div class="stat-line"><span>${t.date} ${t.meal_type_name}</span><strong>${escapeHtml(t.temperature)}</strong></div>`).join('') : '<div class="stats-empty">온도 기록이 없습니다.</div>';
  const backdataCols = [
    { key: 'date', label: '날짜' },
    { key: 'weekday', label: '요일' },
    { key: 'meal_type_name', label: '구분' },
    { key: 'planned_count', label: '계획', render: v => numberText(v) },
    { key: 'actual_count', label: '실제', render: v => v === null ? '-' : numberText(v) },
    { key: 'actual_input', label: '식수 입력', render: v => v ? '✓' : '미입력' },
    { key: 'actual_recorded_at', label: '입력 시각', render: v => v ? v.slice(0, 16).replace('T', ' ') : '-' },
    { key: 'meal_plan_output', label: '식단표', render: v => v ? '✓' : '미출력' },
    { key: 'cooking_output', label: '조리지시서', render: v => v ? '✓' : '미출력' },
    { key: 'preservation_completed', label: '보존식', render: v => v ? '✓' : '미완료' },
    { key: 'preservation_manager', label: '보존식 담당', render: v => v ?? '-' },
    { key: 'preservation_temperature', label: '냉동고 온도', render: v => v ?? '-' },
  ];
  root.innerHTML = `
    <div class="kpi-grid">${kpis.join('')}</div>
    ${breakdownHtml}
    <div class="chart-grid">
      ${chartContainer({ title: '월별 기록 완료율 추세', subtitle: `${current.start} ~ ${current.end}`, body: trendHtml })}
      ${chartContainer({ title: '기록 누락 현황', subtitle: '미입력·미출력·미완료 건수', body: `<div class="stat-list">${gapHtml}</div>` })}
      ${chartContainer({ title: '실제 식수 지연 입력', subtitle: '배식 다음 날 이후 입력', body: `<div class="stat-list">${lateHtml}</div>` })}
      ${chartContainer({ title: '보존식 담당자별 기록', subtitle: `수거 ${p.collected_count}건 · 폐기 ${p.disposed_count}건`, body: `<div class="stat-list">${managerHtml}</div>` })}
      ${chartContainer({ title: '냉동고 온도 기록', subtitle: '최근 10건', body: `<div class="stat-list">${tempHtml}</div>` })}
      ${chartContainer({ title: '백데이터', subtitle: '배식별 운영 상태', body: '<div class="stats-empty">백데이터 보기 버튼으로 확인합니다.</div>', actions: `<button type="button" class="link-button" id="operations-backdata-btn">백데이터 보기</button>` })}
    </div>`;
  $('#operations-backdata-btn', root)?.addEventListener('click', () => {
    openDetailDrawer({ title: '운영 기록 백데이터', subtitle: `${current.start} ~ ${current.end}`, body: '<div id="drawer-backdata"></div>', footer: '<button type="button" class="primary-button" id="drawer-close-btn">닫기</button>' });
    renderStatisticsDataTable($('#drawer-backdata'), { columns: backdataCols, rows: data.backdata, pageSize: 10, filename: 'operation_backdata' });
    $('#drawer-close-btn').addEventListener('click', closeDetailDrawer);
  });
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
    else if(state.masterDataTab==='actual-meal-upload') renderActualMealUploadView(root);
    else renderSetupImportView(root);
  }catch(e){root.innerHTML=`<div class="form-error">${escapeHtml(e.message)}</div>`;}
}

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
    <div class="stat-mini-card"><strong>제외/오류</strong><span>${numberText(summary.excluded_count)} / ${numberText(summary.error_count)}</span></div>
  </div></div>`;
}

function renderActualMealRows(){
  const result=$('#actual-meal-result');const upload=state.actualMealUpload;if(!result||!upload)return;
  const rows=upload.rows||[];const pageSize=50;const page=upload.page||0;const pageCount=Math.max(1,Math.ceil(rows.length/pageSize));const visible=rows.slice(page*pageSize,(page+1)*pageSize);
  const statusClass={신규:'badge-ok',수정:'badge-warn','변경 없음':'badge-inactive',오류:'badge-fail',제외:'badge-inactive'};
  const table=`<div class="table-wrap"><table class="data-table"><thead><tr><th>Excel 행</th><th>일자</th><th>배식유형</th><th>업로드 실제식수</th><th>기존 DB 실제식수</th><th>반영 후 실제식수</th><th>특이사항</th><th>처리 예정 상태</th><th>오류 내용</th></tr></thead><tbody>${visible.map(row=>`<tr><td>${row.excel_row}</td><td>${escapeHtml(row.date||'-')}</td><td>${escapeHtml(row.meal_type_name||row.meal_type||'-')}</td><td>${numberText(row.upload_count)}</td><td>${row.existing_count===null||row.existing_count===undefined?'-':numberText(row.existing_count)}</td><td>${row.error?'-':numberText(row.upload_count)}</td><td>${escapeHtml(row.note||'')}</td><td><span class="badge ${statusClass[row.status]||''}">${escapeHtml(row.status||'-')}</span></td><td class="form-error">${escapeHtml(row.error||'')}</td></tr>`).join('')}</tbody></table></div>`;
  const canApply=!upload.errors?.length&&upload.summary.error_count===0&&upload.token;
  const pager=`<div class="table-tools"><span class="muted">${rows.length?`${page*pageSize+1}~${Math.min((page+1)*pageSize,rows.length)}행 / 전체 ${rows.length}행`: '표시할 데이터가 없습니다.'}</span><button class="secondary-button" id="actual-meal-prev" ${page<=0?'disabled':''}>이전</button><button class="secondary-button" id="actual-meal-next" ${page>=pageCount-1?'disabled':''}>다음</button><button class="primary-button" id="actual-meal-apply" ${canApply?'':'disabled'}>DB 반영</button></div>`;
  result.innerHTML=renderActualMealSummary({...upload.summary,filename:upload.filename})+pager+table;
  $('#actual-meal-prev')?.addEventListener('click',()=>{upload.page=Math.max(0,page-1);renderActualMealRows();});
  $('#actual-meal-next')?.addEventListener('click',()=>{upload.page=Math.min(pageCount-1,page+1);renderActualMealRows();});
  $('#actual-meal-apply')?.addEventListener('click',applyActualMealUpload);
}

async function previewActualMealUpload(){
  const file=$('#actual-meal-file').files[0];if(!file){toast('식수 정보 XLSX 파일을 선택해 주세요.',true);return;}
  const data=new FormData();data.append('file',file);const result=$('#actual-meal-result');result.innerHTML='<div class="result-card">파일을 검증하고 있습니다.</div>';
  try{const response=await api('/api/setup/actual-meals/preview',{method:'POST',body:data});state.actualMealUpload={...response,filename:file.name,page:0};renderActualMealRows();}
  catch(e){result.innerHTML=`<div class="result-card"><h3 class="form-error">검증 실패</h3><p>${escapeHtml(e.message)}</p></div>`;toast(e.message,true);}
}

async function applyActualMealUpload(){
  const upload=state.actualMealUpload;if(!upload?.token)return;
  if(!confirm(`검증된 ${numberText(upload.summary.candidate_count)}건의 식수 정보를 DB에 반영하시겠습니까? 파일에 없는 기존 데이터는 유지됩니다.`))return;
  const button=$('#actual-meal-apply');if(button){button.disabled=true;button.textContent='반영 중…';}
  try{const response=await api('/api/setup/actual-meals/apply',json('POST',{token:upload.token}));const result=response.result;$('#actual-meal-result').innerHTML=`<div class="result-card"><h3>반영 완료</h3><p>반영 일시 ${new Date(response.completed_at).toLocaleString('ko-KR')}</p><div class="stats-mini"><div class="stat-mini-card"><strong>전체 반영 후보</strong><span>${numberText(result.candidate_count)}건</span></div><div class="stat-mini-card"><strong>신규 등록</strong><span>${numberText(result.new_count)}건</span></div><div class="stat-mini-card"><strong>수정</strong><span>${numberText(result.update_count)}건</span></div><div class="stat-mini-card"><strong>변경 없음</strong><span>${numberText(result.unchanged_count)}건</span></div><div class="stat-mini-card"><strong>제외</strong><span>${numberText(result.excluded_count)}건</span></div><div class="stat-mini-card"><strong>실패</strong><span>${numberText(result.failed_count)}건</span></div></div></div>`;toast('식수 정보 반영을 완료했습니다.');}
  catch(e){if(button){button.disabled=false;button.textContent='DB 반영';}toast(e.message,true);}
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
      <div class="table-tools"><input id="master-search" placeholder="메뉴 검색" value="${escapeHtml(curVal)}"><button class="secondary-button" id="new-menu">＋ 메뉴</button></div>
      <div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>메뉴명</th><th>역할</th><th>레시피</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-menu-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.role)}</td><td>${r.recipe_count}개</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div>
    </section>
    <aside id="master-editor" class="master-editor-panel"></aside>
  </div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  $('#master-search').addEventListener('input',e=>{clearTimeout(window.masterTimer);window.masterTimer=setTimeout(()=>renderMenusMaster(root,e.target.value),250)});
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
  return `<article class="master-history-card"><header><strong>${date} · ${mealLabel} · 실제 ${actualCount}</strong>${recipeName?`<span class="master-history-recipe">${escapeHtml(recipeName)}</span>`:''}</header><div class="master-history-menus">${item.menus.map(menu=>`<button type="button" class="master-history-menu ${menu.meal_service_menu_id===targetId?'target':''}" data-history-menu="${menu.meal_service_menu_id}">${menu.is_representative?'<span class="representative-mark" title="대표 메뉴">★</span>':''}${escapeHtml(menu.name)}</button>`).join('')}</div><div class="master-history-snapshot" data-snapshot-for="${item.meal_service_id}"></div></article>`;
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
    <section class="master-list-panel"><div class="table-tools"><input id="master-search" placeholder="재료 검색" value="${escapeHtml(curVal)}"><button class="secondary-button" id="new-ingredient">＋ 재료</button></div><div class="table-wrap master-list-wrap"><table class="data-table"><thead><tr><th>재료명</th><th>통계분석군</th><th>단위</th><th>상태</th></tr></thead><tbody>${rows.map(r=>`<tr data-ingredient-master="${r.id}" class="${r.id===state.masterSelectionId?'selected-row':''}"><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.stat_group)}</td><td>${escapeHtml(r.default_unit||'')}</td><td>${r.active?'사용':'미사용'}</td></tr>`).join('')}</tbody></table></div></section>
    <aside id="master-editor" class="master-editor-panel"></aside></div>`;
  const si=$('#master-search');if(hadFocus&&si){si.focus();if(curCursor!=null)si.setSelectionRange(curCursor,curCursor);if(curScroll!=null)si.scrollTop=curScroll;}
  $('#master-search').addEventListener('input',e=>{clearTimeout(window.masterTimer);window.masterTimer=setTimeout(()=>renderIngredientsMaster(root,e.target.value),250)});
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
  const toolbar=`<div class="ingredient-usage-toolbar"><strong>사용 메뉴 ${usage.total}개</strong><input id="ingredient-usage-search" placeholder="메뉴 검색" value="${escapeHtml(state.masterIngredientUsageQuery)}"></div>`;
  if(usage.loading&&!usage.items.length){root.innerHTML=toolbar+'<div class="master-ingredient-loading">사용 메뉴를 불러오는 중...</div>';bindIngredientUsageSearch();return;}
  if(!usage.items.length){root.innerHTML=toolbar+'<div class="master-history-empty">사용 메뉴가 없습니다.<small>현재 기준 레시피나 과거 식단에서 이 재료가 사용된 기록이 없습니다.</small></div>';bindIngredientUsageSearch();return;}
  root.innerHTML=toolbar+`<div class="ingredient-usage-list">${usage.items.map(item=>{const recent=item.has_historical_usage?`최근 ${item.last_used.date.replaceAll('-','.')} · ${escapeHtml({LUNCH:'중식',DINNER:'석식'}[item.last_used.meal_type]||item.last_used.meal_type)} · 실제 식수 ${item.last_used.actual_count==null?'-':`${numberText(item.last_used.actual_count)}명`} · ${item.historical_usage_count}회`:'최근 사용 없음';const badges=[item.menu_role,item.menu_canonical_name?`집계: ${item.menu_canonical_name}`:null].filter(Boolean);return `<article class="ingredient-usage-card"><div class="ingredient-usage-card-content"><div class="ingredient-usage-card-title"><strong>${escapeHtml(item.menu_name)}</strong><span class="ingredient-usage-badges">${badges.map(badge=>`<span>${escapeHtml(badge)}</span>`).join('')}</span></div><div class="ingredient-usage-card-meta">${recent}</div></div></article>`;}).join('')}</div>${usage.hasMore?'<button class="secondary-button master-history-more" id="ingredient-usage-more">더 보기</button>':''}`;
  bindIngredientUsageSearch();$('#ingredient-usage-more')?.addEventListener('click',()=>loadIngredientUsage(usage.ingredientId,true));
}
function bindIngredientUsageSearch(){const input=$('#ingredient-usage-search');if(input)input.addEventListener('input',()=>{state.masterIngredientUsageQuery=input.value;clearTimeout(window.ingredientUsageTimer);window.ingredientUsageTimer=setTimeout(()=>loadIngredientUsage(state.masterIngredientUsage.ingredientId),250);});}
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

let _usersSearchTimer = null;
async function loadUsersList(q) {
  const root = $('#users-root');
  if (!root) return;
  const data = await api(`/api/users?q=${encodeURIComponent(q)}`);
  const rows = data.items;
  root.innerHTML = `<div class="table-tools">
    <input id="users-search" placeholder="사용자 ID 또는 이름 검색" value="${escapeHtml(q)}">
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
  let composing = false;
  si.addEventListener('compositionstart', () => { composing = true; });
  si.addEventListener('compositionend', e => { composing = false; clearTimeout(_usersSearchTimer); _usersSearchTimer = setTimeout(() => loadUsersList(e.target.value), 200); });
  si.addEventListener('input', e => { if (composing) return; clearTimeout(_usersSearchTimer); _usersSearchTimer = setTimeout(() => loadUsersList(e.target.value), 200); });
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
      await loadUsersList($('#users-search')?.value || '');
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
      await loadUsersList($('#users-search')?.value || '');
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
      await loadUsersList($('#users-search')?.value || '');
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
      await loadUsersList($('#users-search')?.value || '');
    } catch (ex) { closeModal(); toast(ex.message, true); }
  });
}

async function confirmActivate(user) {
  try {
    await api(`/api/users/${user.id}`, json('PUT', { active: true }));
    toast('사용자 계정이 사용 재개되었습니다.');
    await loadUsersList($('#users-search')?.value || '');
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
  try {
    await api('/api/admin/backups', { method: 'POST' });
    toast('시스템 데이터 백업이 생성되었습니다.');
    await loadBackupList();
  } catch (e) {
    toast(e.message, true);
  } finally {
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
  try {
    let url = '/api/admin/archives';
    const params = [];
    if (dateFrom) params.push(`date_from=${dateFrom}`);
    if (dateTo) params.push(`date_to=${dateTo}`);
    if (params.length) url += '?' + params.join('&');
    const result = await api(url, { method: 'POST' });
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
  const q = ($('#orders-search')?.value || '').trim().toLowerCase();
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

document.addEventListener('DOMContentLoaded',()=>init().catch(e=>toast(e.message,true)));
