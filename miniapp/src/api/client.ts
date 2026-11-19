import Taro from '@tarojs/taro';
import type { Confidence, DiagnosisReport, Direction } from '../data/consultation';

// 开发：微信开发者工具里把"不校验合法域名"勾上即可用本机地址。
// 上线：改成你备案后的 HTTPS 域名，并加入小程序合法域名白名单。
const API_BASE = 'http://127.0.0.1:8000/api';

export interface ChatMessageResult {
  type: 'message';
  conversationId: string;
  text: string;
  suggestions: string[];
}

export interface ChatReportResult {
  type: 'report';
  conversationId: string;
  report: DiagnosisReport;
}

export interface ChatConfirmationResult {
  type: 'confirmation';
  conversationId: string;
  text: string;
  suggestions: string[];
}

export type ChatResult = ChatMessageResult | ChatReportResult | ChatConfirmationResult;

interface BackendDirection {
  title: string;
  confidence: string;
  summary: string;
  causes: string[];
  actions: string[];
}

interface BackendReport {
  sceneLabel: string;
  painPoint: string;
  painQuote: string;
  costValue: string;
  costUnit: string;
  costNote: string;
  directions: BackendDirection[];
  openQuestions?: string[];
}

function normConfidence(value: string): Confidence {
  return value === '高' || value === '中' || value === '低' ? value : '中';
}

function mapReport(raw: BackendReport): DiagnosisReport {
  const directions: Direction[] = (raw.directions || []).map((d, index) => ({
    id: `dir-${index + 1}`,
    title: d.title,
    confidence: normConfidence(d.confidence),
    summary: d.summary,
    causes: d.causes || [],
    actions: d.actions || [],
  }));
  return {
    sceneId: raw.sceneLabel || 'general',
    sceneLabel: raw.sceneLabel || '经营问题',
    painPoint: raw.painPoint,
    painQuote: raw.painQuote,
    costValue: raw.costValue,
    costUnit: raw.costUnit,
    costNote: raw.costNote,
    directions,
    openQuestions: raw.openQuestions || [],
    createdAt: Date.now(),
  };
}

// ---- 微信登录 ----
// wx.login 拿 code，后端换 openid 后发一个 token；报告按用户归属，换设备、清缓存也能找回。
// 后端没配 AppID/AppSecret 时登录返回 503，这里按匿名继续用，只是报告只能在本机找回。
const TOKEN_KEY = 'wenti.auth.token';
let loginTask: Promise<string | null> | null = null;
// 后端没开登录（503）时这次启动不再反复尝试，免得每个请求都多等一次
let loginDisabled = false;

function cachedToken(): string | null {
  try {
    return Taro.getStorageSync(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

async function doLogin(): Promise<string | null> {
  try {
    const { code } = await Taro.login({ timeout: 10000 });
    if (!code) return null;
    const res = await Taro.request({
      url: `${API_BASE}/login`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { code },
      timeout: 10000,
    });
    if (res.statusCode === 503) loginDisabled = true;
    const token = res.statusCode === 200 ? (res.data as any)?.token : null;
    if (!token) return null;
    Taro.setStorageSync(TOKEN_KEY, token);
    return token;
  } catch {
    return null;
  }
}

/** 已有 token 直接用，否则登录一次；并发调用共用同一次登录。登录失败返回 null，按匿名请求 */
export function ensureLogin(force = false): Promise<string | null> {
  if (!force) {
    const token = cachedToken();
    if (token) return Promise.resolve(token);
  } else {
    try {
      Taro.removeStorageSync(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  }
  if (loginDisabled) return Promise.resolve(null);
  if (!loginTask) {
    loginTask = doLogin().finally(() => {
      loginTask = null;
    });
  }
  return loginTask;
}

type RequestOptions = Omit<Taro.request.Option, 'url' | 'header'> & { path: string };

/** 带上登录态发请求；token 失效（401）时重新登录再试一次 */
async function request(options: RequestOptions): Promise<Taro.request.SuccessCallbackResult<any>> {
  const { path, ...rest } = options;
  const send = (token: string | null) =>
    Taro.request({
      ...rest,
      url: `${API_BASE}${path}`,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  const token = await ensureLogin();
  const res = await send(token);
  if (res.statusCode !== 401) return res;
  const fresh = await ensureLogin(true);
  return fresh ? send(fresh) : res;
}

async function post(path: string, data: Record<string, unknown>): Promise<any> {
  const res = await request({
    path,
    method: 'POST',
    data,
    // 生成报告要等模型输出整份 JSON，失败还会重试一次，给足时间
    timeout: 120000,
  });
  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`request failed: ${res.statusCode}`);
  }
  return res.data;
}

function mapChatResult(data: any): ChatResult {
  if (data.type === 'report') {
    return { type: 'report', conversationId: data.conversationId, report: mapReport(data.report) };
  }
  if (data.type === 'confirmation') {
    return {
      type: 'confirmation',
      conversationId: data.conversationId,
      text: data.text,
      suggestions: data.suggestions || ['对，就是这个', '不对，有点问题'],
    };
  }
  return { type: 'message', conversationId: data.conversationId, text: data.text, suggestions: data.suggestions || [] };
}

export async function postChat(conversationId: string | null, message: string): Promise<ChatResult> {
  return mapChatResult(await post('/chat', { conversationId, message }));
}

export async function confirmUnderstanding(conversationId: string): Promise<ChatResult> {
  return mapChatResult(await post('/chat', { conversationId, message: '', action: 'confirm_understanding' }));
}

export async function correctUnderstanding(conversationId: string, correction: string): Promise<ChatResult> {
  return mapChatResult(await post('/chat', { conversationId, message: correction, action: 'correct_understanding' }));
}

export async function submitReportFeedback(
  conversationId: string,
  action: 'accurate' | 'correct',
  correction = '',
): Promise<DiagnosisReport | null> {
  const data = await post('/report-feedback', { conversationId, action, correction });
  return data.type === 'report' ? mapReport(data.report) : null;
}

export interface LatestReport {
  conversationId: string;
  report: DiagnosisReport;
  feedback: 'accurate' | 'corrected' | null;
  /** 用户两次补充的原话，按时间先后 */
  supplements: string[];
  /** 保存过这份报告时为保存用的手机号（打码后） */
  savedPhone: string | null;
}

/**
 * 最后生成的那份报告。传 conversationId 取这次问诊的；传 null 按登录用户取他最近一次的
 * （本机没有会话时用，比如换了手机或清了缓存）。没有报告返回 null，网络或服务出错会抛错。
 */
export async function fetchLatestReport(conversationId: string | null): Promise<LatestReport | null> {
  if (!conversationId && !(await ensureLogin())) return null;
  const res = await request({
    path: '/report',
    method: 'GET',
    data: conversationId ? { conversationId } : {},
    timeout: 10000,
  });
  // 404：还没有报告；401/403：没登录或会话不属于当前用户，都按没有处理
  if (res.statusCode === 404 || res.statusCode === 401 || res.statusCode === 403) return null;
  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`request failed: ${res.statusCode}`);
  }
  const data = res.data as any;
  return {
    conversationId: data.conversationId,
    report: { ...mapReport(data.report), createdAt: data.createdAt },
    feedback: data.feedback ?? null,
    supplements: data.supplements || [],
    savedPhone: data.savedPhone || null,
  };
}

export async function postLead(
  conversationId: string,
  channel: 'wechat' | 'sms',
  phone: string,
): Promise<void> {
  await post('/lead', { conversationId, channel, phone });
}

// ---- 保存报告：手机号 + 短信验证码注册账号 ----

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`request failed: ${status}`);
  }
}

async function postStrict(path: string, data: Record<string, unknown>): Promise<any> {
  const res = await request({ path, method: 'POST', data, timeout: 15000 });
  if (res.statusCode < 200 || res.statusCode >= 300) {
    const detail = (res.data as any)?.detail;
    throw new ApiError(res.statusCode, typeof detail === 'string' ? detail : '');
  }
  return res.data;
}

/** 发短信验证码，返回多少秒后能再发。需要登录；429 冷却中或当天发满，502 短信服务出错 */
export async function sendSmsCode(phone: string): Promise<number> {
  const data = await postStrict('/sms/send', { phone });
  return Number(data.cooldown) || 60;
}

/** 验证码校验通过后绑定手机号并保存报告，返回打码后的手机号。400 表示验证码不对或已过期 */
export async function saveReportWithPhone(
  conversationId: string,
  phone: string,
  code: string,
  directions: string[],
): Promise<string> {
  const data = await postStrict('/report/save', { conversationId, phone, code, directions });
  return data.phone || '';
}

// ---- 历史报告 ----

export interface SavedReport {
  conversationId: string;
  savedAt: number;
  /** 保存时验证的手机号，打码后 */
  savedPhone: string;
  /** consulted：这次问诊后还联系过 FDE 顾问 */
  status: 'saved' | 'consulted';
  /** 保存时选中的方案方向标题 */
  directions: string[];
  feedback: 'accurate' | 'corrected' | null;
  report: DiagnosisReport;
}

export interface SavedReports {
  items: SavedReport[];
  /** 账号绑定的手机号，打码后 */
  accountPhone: string | null;
}

/** 登录用户保存过的报告，最近保存的在前。没登录（后端没开登录）时返回空列表，网络或服务出错会抛错 */
export async function fetchSavedReports(): Promise<SavedReports> {
  if (!(await ensureLogin())) return { items: [], accountPhone: null };
  const res = await request({ path: '/reports', method: 'GET', timeout: 10000 });
  if (res.statusCode === 401) return { items: [], accountPhone: null };
  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`request failed: ${res.statusCode}`);
  }
  const data = res.data as any;
  return {
    accountPhone: data.accountPhone || null,
    items: (data.items || []).map((item: any) => ({
      conversationId: item.conversationId,
      savedAt: item.savedAt,
      savedPhone: item.savedPhone,
      status: item.status === 'consulted' ? 'consulted' : 'saved',
      directions: item.directions || [],
      feedback: item.feedback ?? null,
      report: mapReport(item.report),
    })),
  };
}

/** 从历史报告里删掉一份（只是不再列出，问诊记录保留） */
export async function deleteSavedReport(conversationId: string): Promise<void> {
  const res = await request({ path: `/reports/${encodeURIComponent(conversationId)}`, method: 'DELETE', timeout: 10000 });
  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`request failed: ${res.statusCode}`);
  }
}
