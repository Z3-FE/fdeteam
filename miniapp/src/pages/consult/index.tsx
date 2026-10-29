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
import { AIAvatar, IconClock, IconSend } from '../../components/icons';
import { navigate } from '../../utils/nav';
import { postChat } from '../../api/client';

export default function Consult() {
  const [session, setSession] = useState<ConsultationSession>(() => loadSession());
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [scrollInto, setScrollInto] = useState('');
  const finished = session.report !== null;
  const completed = finished && !thinking;

  useEffect(() => {
    const last = session.messages[session.messages.length - 1];
    if (last) setScrollInto(`msg-${last.id}`);
  }, [session.messages.length, thinking]);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || thinking || finished) return;
      const userMessage: ChatMessage = { id: createMessageId('user'), role: 'user', text };
      const withUser: ConsultationSession = {
        ...session,
        messages: [...session.messages, userMessage],
        answers: [...session.answers, text],
      };
      saveSession(withUser);
      setSession(withUser);
      setDraft('');
      setThinking(true);
      postChat(session.conversationId, text)
        .then((result) => {
          setThinking(false);
          setSession((prev) => {
            const next: ConsultationSession =
              result.type === 'report'
                ? { ...prev, conversationId: result.conversationId, report: result.report }
                : {
                    ...prev,
                    conversationId: result.conversationId,
                    messages: [...prev.messages, { id: createMessageId('ai'), role: 'ai', text: result.text }],
                  };
            saveSession(next);
            return next;
          });
        })
        .catch(() => {
          setThinking(false);
          Taro.showToast({ title: '网络开小差了，再发一次', icon: 'none' });
        });
    },
    [finished, session, thinking],
  );

  const chips = session.answers.length === 0 && !completed && !thinking ? SCENE_CHIPS : [];
  const progress = completed ? 100 : Math.min(90, session.answers.length * 25);
  const sendDisabled = completed || thinking || draft.trim().length === 0;

  return (
    <View className="screen chat">
      <View className="chat-progress">
        <View style={{ width: `${progress}%`, height: '100%', background: 'linear-gradient(90deg,#ffb09a,#ff7a59)' }} />
      </View>

      <ScrollView className="chat-scroll" scrollY scrollIntoView={scrollInto} scrollWithAnimation>
        <View className="chat-date">今天</View>
        {session.messages.map((m) => (
          <View
            key={m.id}
            id={`msg-${m.id}`}
            className={`bubble-row ${m.role === 'ai' ? 'bubble-row-ai' : 'bubble-row-user'}`}
          >
            {m.role === 'ai' && <AIAvatar size={32} />}
            <View className={`bubble ${m.role === 'ai' ? 'bubble-ai' : 'bubble-user'}`}>{m.text}</View>
          </View>
        ))}
        {thinking && (
          <View className="bubble-row bubble-row-ai">
            <AIAvatar size={32} />
            <View className="bubble bubble-ai bubble-typing">
              <Text className="typing-label">正在思考…</Text>
            </View>
          </View>
        )}
        {completed && (
          <View className="chat-done">
            <View className="chat-done-card">
              <View className="chat-done-icon">
                <Text className="qb-icon">✦</Text>
              </View>
              <View>
                <View className="chat-done-title">诊断报告已经整理好了</View>
                <View className="chat-done-text">核心问题、代价和可切入的方向都在里面，2 分钟能看完。</View>
              </View>
            </View>
            <View className="btn btn-primary" onClick={() => navigate('report')}>
              查看诊断报告
            </View>
          </View>
        )}
      </ScrollView>

      <View className="composer-wrap">
        {chips.length > 0 && (
          <ScrollView className="chips" scrollX>
            {chips.map((chip) => (
              <View key={chip} className="chip" onClick={() => send(chip)}>
                {chip}
              </View>
            ))}
          </ScrollView>
        )}
        <View className={`composer ${completed ? 'composer-done' : ''}`}>
          <Input
            className="composer-input"
            value={draft}
            disabled={completed || thinking}
            placeholder={completed ? '诊断已完成，点上面查看报告' : '用大白话说就行…'}
            confirmType="send"
            onInput={(e) => setDraft(e.detail.value)}
            onConfirm={() => send(draft)}
          />
          <View className={`composer-send ${sendDisabled ? 'is-disabled' : ''}`} onClick={() => !sendDisabled && send(draft)}>
            <IconSend />
          </View>
        </View>
        <View className="composer-hint">
          <IconClock />
          一次只问一件事，聊几轮就能出报告
        </View>
      </View>
    </View>
  );
}
