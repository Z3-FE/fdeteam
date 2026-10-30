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

export type ChatResult = ChatMessageResult | ChatReportResult;

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

async function post(path: string, data: Record<string, unknown>): Promise<any> {
  const res = await Taro.request({
    url: `${API_BASE}${path}`,
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
    data,
  });
  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`request failed: ${res.statusCode}`);
  }
  return res.data;
}

export async function postChat(conversationId: string | null, message: string): Promise<ChatResult> {
  const data = await post('/chat', { conversationId, message });
  if (data.type === 'report') {
    return { type: 'report', conversationId: data.conversationId, report: mapReport(data.report) };
  }
  return { type: 'message', conversationId: data.conversationId, text: data.text, suggestions: data.suggestions || [] };
}

export async function postLead(
  conversationId: string,
  channel: 'wechat' | 'sms',
  phone: string,
): Promise<void> {
  await post('/lead', { conversationId, channel, phone });
}
