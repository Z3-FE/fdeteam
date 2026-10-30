import Taro from '@tarojs/taro';

export const SCHEMA_VERSION = 2;
export const STORAGE_KEY = 'wenti.consultation.v2';

export type Confidence = '高' | '中' | '低';

export interface ChatMessage {
  id: string;
  role: 'ai' | 'user';
  text: string;
}

export interface Direction {
  id: string;
  title: string;
  confidence: Confidence;
  summary: string;
  causes: string[];
  actions: string[];
}

export interface DiagnosisReport {
  sceneId: string;
  sceneLabel: string;
  painPoint: string;
  painQuote: string;
  costValue: string;
  costUnit: string;
  costNote: string;
  directions: Direction[];
  openQuestions?: string[];
  createdAt: number;
}

export interface Lead {
  channel: 'wechat' | 'sms';
  phone: string;
  createdAt: number;
}

export interface ConsultationSession {
  version: number;
  conversationId: string | null;
  messages: ChatMessage[];
  answers: string[];
  suggestions: string[];
  report: DiagnosisReport | null;
  lead: Lead | null;
}

export const OPENING_MESSAGE =
  '你好，我帮你把公司里最头疼的问题理清楚，免费的。咱们一步步来，你用大白话说就行——最近有哪件事，让你觉得特别费时间或费钱？';

export const SCENE_CHIPS = ['客户和订单太乱', '库存老是说不准', '人手不够用', '账目和成本看不清'];

export function createMessageId(prefix = 'msg'): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export function createSession(): ConsultationSession {
  return {
    version: SCHEMA_VERSION,
    conversationId: null,
    messages: [{ id: 'ai-opening', role: 'ai', text: OPENING_MESSAGE }],
    answers: [],
    suggestions: [],
    report: null,
    lead: null,
  };
}

export function loadSession(): ConsultationSession {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEY);
    if (!raw) return createSession();
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!parsed || parsed.version !== SCHEMA_VERSION || !Array.isArray(parsed.messages)) {
      return createSession();
    }
    return parsed as ConsultationSession;
  } catch {
    return createSession();
  }
}

export function saveSession(session: ConsultationSession): void {
  try {
    Taro.setStorageSync(STORAGE_KEY, JSON.stringify(session));
  } catch {
    /* storage unavailable */
  }
}

export function resetSession(): ConsultationSession {
  const session = createSession();
  saveSession(session);
  return session;
}

export function formatReportDate(timestamp: number): string {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

export function maskPhone(phone: string): string {
  if (!/^1\d{10}$/.test(phone)) return phone;
  return `${phone.slice(0, 3)}****${phone.slice(7)}`;
}
