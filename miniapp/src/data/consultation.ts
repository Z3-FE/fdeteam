import Taro from '@tarojs/taro';

export const SCHEMA_VERSION = 5;
export const STORAGE_KEY = 'wenti.consultation.v5';

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
  /** 方便沟通的时间，如"今天方便" */
  time?: string;
  createdAt: number;
}

export interface ConsultationSession {
  version: number;
  conversationId: string | null;
  messages: ChatMessage[];
  answers: string[];
  suggestions: string[];
  confirmation: string | null;
  // confirm/correct：问诊结束后生成报告；revise：看完报告后补充，修正已有报告（只能一次）
  generationRequest: { action: 'confirm' | 'correct' | 'revise'; correction?: string } | null;
  /** 用户在补充信息页写的背景，报告页和顾问摘要里展示 */
  supplementNote?: string;
  reportFeedback: 'accurate' | 'corrected' | null;
  report: DiagnosisReport | null;
  lead: Lead | null;
  /** 保存报告时验证过的手机号（打码后），有值说明这份报告已保存 */
  savedPhone?: string;
  /** 报告页选中的方案方向标题，保存报告时一起提交 */
  selectedDirections?: string[];
}

export const OPENING_MESSAGE = '我们一步步把最卡壳的问题理清楚。最近哪件事最费时间，或最费钱？';

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
    confirmation: null,
    generationRequest: null,
    reportFeedback: null,
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

// 保存报告时验证过的手机号（明文），独立于问诊会话存放，重新问诊后联系顾问也能直接带出
const ACCOUNT_PHONE_KEY = 'qb_account_phone';

export function loadAccountPhone(): string {
  try {
    const value = Taro.getStorageSync(ACCOUNT_PHONE_KEY);
    return typeof value === 'string' ? value : '';
  } catch {
    return '';
  }
}

export function saveAccountPhone(phone: string): void {
  try {
    Taro.setStorageSync(ACCOUNT_PHONE_KEY, phone);
  } catch {
    /* storage unavailable */
  }
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
