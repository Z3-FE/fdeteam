import Taro from '@tarojs/taro';
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
import { AIAvatar, IconSend } from '../../components/icons';
import { navigate } from '../../utils/nav';
import { confirmUnderstanding, correctUnderstanding, postChat, type ChatResult } from '../../api/client';

// 一般 6 轮左右问完，进度条按这个分段
const ROUNDS = 6;

export default function Consult() {
  const [session, setSession] = useState<ConsultationSession>(() => loadSession());
  const [draft, setDraft] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [thinking, setThinking] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [scrollInto, setScrollInto] = useState('');
  const awaitingConfirmation = session.confirmation !== null;
  const finished = session.report !== null;
  const completed = finished && !thinking;

  // 每次有新内容都滚到底部锚点，选项和完成卡片也在消息流里，要一起露出来
  useEffect(() => {
    setScrollInto(`chat-end-${session.messages.length}-${thinking ? 1 : 0}`);
  }, [session.messages.length, thinking]);

  const applyResult = useCallback((result: ChatResult) => {
    setThinking(false);
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
          messages: [...prev.messages, { id: createMessageId('ai'), role: 'ai', text: result.text }],
        };
      }
      saveSession(next);
      if (result.type === 'report') navigate('generating');
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

  const acceptUnderstanding = () => {
    if (!session.conversationId || thinking) return;
    setThinking(true);
    confirmUnderstanding(session.conversationId).then(applyResult).catch(() => {
      setThinking(false);
      Taro.showToast({ title: '网络开小差了，再点一次', icon: 'none' });
    });
  };

  const submitCorrection = () => {
    const text = draft.trim();
    if (!session.conversationId || !text || thinking) return;
    setThinking(true);
    correctUnderstanding(session.conversationId, text).then(applyResult).catch(() => {
      setThinking(false);
      Taro.showToast({ title: '网络开小差了，再提交一次', icon: 'none' });
    });
  };

  const chips =
    thinking || completed || awaitingConfirmation
      ? []
      : session.answers.length === 0 && session.suggestions.length === 0
        ? SCENE_CHIPS
        : session.suggestions;
  const rounds = session.answers.length;
  const doneSegments = completed ? ROUNDS : Math.min(ROUNDS - 1, rounds);
  const statusText = completed
    ? '报告整理好了'
    : rounds === 0
      ? '回答几个问题就能出报告'
      : `已聊 ${rounds} 轮，一般 6 轮左右出报告`;
  const sendDisabled = completed || thinking || awaitingConfirmation || draft.trim().length === 0;

  // 正在说话的那一条 AI 消息才带头像，之前的退到次要层级
  let lastAiIndex = -1;
  session.messages.forEach((m, i) => {
    if (m.role === 'ai') lastAiIndex = i;
  });
  const lastIsAi = lastAiIndex === session.messages.length - 1;

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
    <View className="screen chat">
      <View className="chat-status">
        <View className="chat-steps">
          {Array.from({ length: ROUNDS }).map((_, i) => (
            <Text key={i} className={`chat-step ${i < doneSegments ? 'is-done' : ''} ${i === doneSegments && !completed ? 'is-now' : ''}`} />
          ))}
        </View>
        <Text className="chat-status-text">{statusText}</Text>
      </View>

      <ScrollView className="chat-scroll" scrollY scrollIntoView={scrollInto} scrollWithAnimation>
        {session.messages.map((m, i) =>
          m.role === 'ai' ? (
            <View key={m.id} className={`ai-row ${i === lastAiIndex && !thinking ? 'is-current' : ''}`}>
              {i === lastAiIndex && !thinking ? <AIAvatar size={30} active /> : <View className="ai-row-gutter" />}
              <View className="ai-text">{m.text}</View>
            </View>
          ) : (
            <View key={m.id} className="user-row">
              <View className="user-bubble">{m.text}</View>
            </View>
          ),
        )}

        {thinking && (
          <View className="ai-row is-current">
            <AIAvatar size={30} thinking />
            <View className="ai-thinking">
              <Text className="dot" />
              <Text className="dot" />
              <Text className="dot" />
            </View>
          </View>
        )}

        {awaitingConfirmation && !thinking && (
          <View className="confirmation-card">
            <View className="confirmation-title">我先确认一下有没有理解偏</View>
            <View className="confirmation-text">{session.confirmation}</View>
            {!correcting ? (
              <View className="confirmation-actions">
                <View className="btn btn-primary" onClick={acceptUnderstanding}>对，就是这个</View>
                <View className="btn btn-ghost" onClick={() => { setCorrecting(true); setDraft(''); }}>不对，有点问题</View>
              </View>
            ) : (
              <View className="confirmation-correction">
                <View className="confirmation-hint">哪里理解错了？补充一句就行。</View>
                <View className="btn btn-primary" onClick={submitCorrection}>提交并生成报告</View>
              </View>
            )}
          </View>
        )}

        {chips.length > 0 && lastIsAi && (
          <View className="reply-picks">
            <View className="picks">
              {chips.map((chip) => (
                <View
                  key={chip}
                  className={`pick ${picked.includes(chip) ? 'is-picked' : ''}`}
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

        {completed && (
          <View className="chat-done">
            <View className="chat-done-title">诊断报告整理好了</View>
            <View className="chat-done-text">你的核心问题、它的代价和能怎么解决都写在里面，2 分钟能看完。</View>
            <View className="btn btn-primary" onClick={() => navigate('report')}>
              查看诊断报告
            </View>
          </View>
        )}

        <View id={scrollInto} className="chat-end" />
      </ScrollView>

      <View className={`composer-wrap ${completed ? 'is-done' : ''}`}>
        <View className="composer">
          <Input
            className="composer-input"
            value={draft}
            disabled={completed || thinking || (awaitingConfirmation && !correcting)}
            placeholder={completed ? '诊断已完成' : thinking ? '稍等，正在想…' : correcting ? '哪里理解错了？补充一句就行' : '用大白话说就行'}
            confirmType="send"
            onInput={(e) => setDraft(e.detail.value)}
            onConfirm={() => correcting ? submitCorrection() : send(draft)}
          />
          <View
            className={`composer-send ${(correcting ? thinking || !draft.trim() : sendDisabled) ? 'is-disabled' : ''}`}
            onClick={() => correcting ? (!thinking && draft.trim() && submitCorrection()) : (!sendDisabled && send(draft))}
          >
            <IconSend />
          </View>
        </View>
      </View>
    </View>
  );
}
