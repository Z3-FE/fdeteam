import Taro, { useDidShow } from '@tarojs/taro';
import { useCallback, useEffect, useState } from 'react';
import { Input, ScrollView, Text, View } from '@tarojs/components';
import {
  SCENE_CHIPS,
  createMessageId,
  loadSession,
  saveSession,
  type ChatMessage,
  type ConsultationSession,
} from '../../data/consultation';
import { IconSend, IconSpark } from '../../components/icons';
import { navigate } from '../../utils/nav';
import { postChat, type ChatResult } from '../../api/client';

// 思考提示按时间切换（接口只有一次请求，拿不到真实阶段）
const PHASE_AT = [1500, 4000];

// 问几轮由 AI 决定（一般 5–6 轮，最多 8 轮），所以不显示次数。
// 进度线走一条越来越慢的曲线：1 轮约 25%，3 轮约 55%，5 轮约 75%，8 轮约 90%，只有出报告才走满
const progressOf = (answers: number) => Math.min(0.92, 1 - Math.exp(-answers / 3.5));

const stageOf = (answers: number) =>
  answers <= 1 ? '先了解一下情况' : answers <= 3 ? '在找问题的根子' : '差不多了，再确认几个细节';

// 按句子切开，逐句淡入；标点留在句尾
const splitSentences = (text: string) => text.match(/[^。！？!?]+[。！？!?]*/g) || [text];

// 模型偶尔在复述和提问之间空一行，合并成一段显示
const joinLines = (text: string) => text.replace(/\s*\n+\s*/g, '');

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max)}…` : text);

// 一轮 = 一个 AI 问题 + 用户对它的回答
interface Round {
  ai: ChatMessage | null;
  answers: ChatMessage[];
}

function toRounds(messages: ChatMessage[]): Round[] {
  const rounds: Round[] = [];
  for (const m of messages) {
    if (m.role === 'ai' || rounds.length === 0) rounds.push({ ai: m.role === 'ai' ? m : null, answers: [] });
    if (m.role !== 'ai') rounds[rounds.length - 1].answers.push(m);
  }
  return rounds;
}

export default function Consult() {
  const [session, setSession] = useState<ConsultationSession>(() => loadSession());
  const [draft, setDraft] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [thinking, setThinking] = useState(false);
  const [phase, setPhase] = useState(0);
  const [focused, setFocused] = useState(false);
  // 刚收到的那条 AI 回复逐句淡入，历史消息直接显示
  const [freshId, setFreshId] = useState('');
  const [scrollInto, setScrollInto] = useState('');
  // 后端返回 confirmation 表示问完了：留在本页，末尾出"诊断完毕了"，由用户决定直接生成还是先补充
  const awaitingConfirmation = session.confirmation !== null && session.report === null;
  const finished = session.report !== null;
  const completed = finished && !thinking;
  const ended = completed || (awaitingConfirmation && !thinking);

  // 从补充页返回、或看完报告返回时，以本地存的会话为准
  useDidShow(() => {
    setSession(loadSession());
  });

  const rounds = toRounds(session.messages);
  const lastRound = rounds[rounds.length - 1];
  const scrollTarget = ended
    ? 'read-done'
    : thinking
      ? 'read-thinking-anchor'
      : lastRound && lastRound.ai
        ? `read-${lastRound.ai.id}`
        : '';

  // 新问题出现时滚到它的段首，从头往下读，而不是像聊天那样贴底
  useEffect(() => {
    if (scrollTarget) setScrollInto(scrollTarget);
  }, [scrollTarget]);

  useEffect(() => {
    if (!thinking) return undefined;
    setPhase(0);
    const timers = PHASE_AT.map((ms, i) => setTimeout(() => setPhase(i + 1), ms));
    return () => timers.forEach(clearTimeout);
  }, [thinking]);

  const applyResult = useCallback((result: ChatResult) => {
    setThinking(false);
    const aiId = createMessageId('ai');
    if (result.type === 'message') setFreshId(aiId);
    setSession((prev) => {
      let next: ConsultationSession;
      if (result.type === 'report') {
        next = { ...prev, conversationId: result.conversationId, report: result.report, confirmation: null, suggestions: [] };
      } else if (result.type === 'confirmation') {
        next = { ...prev, conversationId: result.conversationId, confirmation: result.text, suggestions: [] };
      } else {
        next = {
          ...prev,
          conversationId: result.conversationId,
          suggestions: result.suggestions,
          messages: [...prev.messages, { id: aiId, role: 'ai', text: result.text }],
        };
      }
      saveSession(next);
      if (result.type === 'report') navigate('report');
      return next;
    });
  }, []);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || thinking || finished || awaitingConfirmation) return;
      const userMessage: ChatMessage = { id: createMessageId('user'), role: 'user', text };
      const withUser: ConsultationSession = {
        ...session,
        messages: [...session.messages, userMessage],
        answers: [...session.answers, text],
      };
      saveSession(withUser);
      setSession(withUser);
      setDraft('');
      setPicked([]);
      setThinking(true);
      postChat(session.conversationId, text)
        .then(applyResult)
        .catch(() => {
          setThinking(false);
          Taro.showToast({ title: '网络开小差了，再发一次', icon: 'none' });
        });
    },
    [applyResult, awaitingConfirmation, finished, session, thinking],
  );

  const chips =
    thinking || ended
      ? []
      : session.answers.length === 0 && session.suggestions.length === 0
        ? SCENE_CHIPS
        : session.suggestions;
  const answerCount = session.answers.length;
  const progress = ended ? 1 : progressOf(answerCount);
  const statusText = completed ? '报告整理好了' : ended ? '诊断完毕了' : stageOf(answerCount);
  const sendDisabled = thinking || draft.trim().length === 0;

  const generateReport = () => {
    if (!session.conversationId) return;
    saveSession({ ...session, generationRequest: { action: 'confirm' }, report: null });
    navigate('generating');
  };
  const lastMessage = session.messages[session.messages.length - 1];
  const lastIsAi = !!lastMessage && lastMessage.role === 'ai';
  const lastAnswer = session.answers[answerCount - 1] || '';
  const thinkingLine = phase === 0 ? `在看：${clip(lastAnswer, 12)}` : phase === 1 ? '在想背后的原因' : '在组织下一个问题';
  const firstRound = rounds.find((r) => r.ai);
  const firstAiId = firstRound && firstRound.ai ? firstRound.ai.id : '';

  // 选项可多选：选中追加到输入框（用"、"连接），再点一次取消并从输入框里去掉
  const toggleChip = (chip: string) => {
    if (picked.includes(chip)) {
      setPicked(picked.filter((c) => c !== chip));
      setDraft(
        draft
          .split('、')
          .filter((part) => part.trim() !== chip)
          .join('、'),
      );
    } else {
      setPicked([...picked, chip]);
      setDraft(draft.trim() ? `${draft.trim()}、${chip}` : chip);
    }
  };

  return (
    <View className="screen chat read">
      <View className="read-status">
        <Text key={statusText} className="read-status-text">
          {statusText}
        </Text>
        <View className="read-progress">
          <View className={`read-progress-fill ${ended ? 'is-full' : ''}`} style={{ width: `${progress * 100}%` }} />
        </View>
        <View className="read-status-fade" />
      </View>

      <ScrollView className="read-scroll" scrollY scrollIntoView={scrollInto} scrollWithAnimation>
        {rounds.map((r, idx) => {
          // 只有最新一轮保持全黑，历史轮次退到背景
          const isLast = idx === rounds.length - 1;
          const fresh = !!r.ai && r.ai.id === freshId;
          const isLead = !!r.ai && r.ai.id === firstAiId;
          const aiText = r.ai ? joinLines(r.ai.text) : '';
          const sentences = r.ai ? splitSentences(aiText) : [];
          return (
            <View key={r.ai ? r.ai.id : `round-${idx}`} className={`read-round ${isLast ? 'is-current' : 'is-past'}`}>
              {r.ai && (
                <View id={`read-${r.ai.id}`} className={`read-para ${isLead ? 'is-lead' : ''}`}>
                  {isLead && sentences.length > 1 ? (
                    // 开场白：前面的铺垫用小字灰色，最后一句真正的问题放大
                    <View className="read-text">
                      <Text className="read-lead">{sentences.slice(0, -1).join('').trim()}</Text>
                      <Text className="read-question">{sentences[sentences.length - 1]}</Text>
                    </View>
                  ) : (
                    <View className="read-text">
                      {fresh
                        ? sentences.map((s, k) => (
                            <Text key={k} className="read-sent" style={{ animationDelay: `${150 + k * 90}ms` }}>
                              {s}
                            </Text>
                          ))
                        : aiText}
                    </View>
                  )}
                </View>
              )}
              {r.answers.map((a) => (
                <View key={a.id} className="read-note">
                  <Text className="read-note-text">{a.text}</Text>
                </View>
              ))}
            </View>
          );
        })}

        {thinking && (
          <View id="read-thinking-anchor" className="read-para read-thinking">
            <View className="read-think-line">
              <Text key={phase} className="read-think-label">
                {thinkingLine}
              </Text>
              <Text className="read-think-dot">.</Text>
              <Text className="read-think-dot">.</Text>
              <Text className="read-think-dot">.</Text>
            </View>
            <View className="read-skel">
              <View className="read-skel-bar" />
              <View className="read-skel-bar" />
              <View className="read-skel-bar" />
            </View>
          </View>
        )}

        {ended && (
          <View id="read-done" className="read-para read-done">
            <View className="read-done-title">{completed ? '报告整理好了' : '诊断完毕了'}</View>
            <View className="read-done-text">
              {completed
                ? '你的核心问题、它的代价和能怎么解决都写在里面，2 分钟能看完。'
                : '需要的信息都问到了。点下面生成报告，大约半分钟；有漏说的，可以先补充一次再生成。'}
            </View>
            <View
              className="btn land-cta read-cta"
              onClick={() => (completed ? navigate('report') : generateReport())}
            >
              <View className="land-cta-glow" />
              <View className="land-cta-beam" />
              <View className="land-cta-inner" />
              <View className="land-cta-label">
                <IconSpark />
                {completed ? '查看诊断报告' : '生成诊断报告'}
              </View>
            </View>
            {!completed && (
              <View className="read-done-more" hoverClass="is-tap" hoverStayTime={60} onClick={() => navigate('supplement')}>
                再补充一下
              </View>
            )}
          </View>
        )}

        <View id="read-end" className="read-end" />
      </ScrollView>

      {!ended && (
      <View className="composer-wrap">
        {chips.length > 0 && lastIsAi && (
          <View className="reply-picks">
            <View className="picks">
              {chips.map((chip) => (
                <View
                  key={chip}
                  className={`pick ${picked.includes(chip) ? 'is-picked' : ''}`}
                  hoverClass="is-tap"
                  hoverStayTime={60}
                  onClick={() => toggleChip(chip)}
                >
                  {picked.includes(chip) && <Text className="pick-check">✓</Text>}
                  {chip}
                </View>
              ))}
            </View>
            <View className="picks-hint">可以多选，也可以在下面自己写</View>
          </View>
        )}
        <View className={`composer ${focused ? 'is-focused' : ''}`}>
          <Input
            className="composer-input"
            value={draft}
            disabled={thinking}
            placeholder={thinking ? '稍等，我想一下' : '用大白话说就行'}
            placeholderClass="composer-placeholder"
            confirmType="send"
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onInput={(e) => setDraft(e.detail.value)}
            onConfirm={() => send(draft)}
          />
          <View
            className={`composer-send ${sendDisabled ? 'is-disabled' : ''}`}
            hoverClass={sendDisabled ? 'none' : 'is-tap'}
            hoverStayTime={60}
            onClick={() => !sendDisabled && send(draft)}
          >
            <IconSend />
          </View>
        </View>
      </View>
      )}
    </View>
  );
}
