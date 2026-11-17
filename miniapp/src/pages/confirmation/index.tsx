import { useState } from 'react';
import { Input, View } from '@tarojs/components';
import { loadSession, saveSession } from '../../data/consultation';
import { redirect } from '../../utils/nav';

export default function Confirmation() {
  const [session] = useState(() => loadSession());
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState('');

  if (!session.conversationId || !session.confirmation) {
    return (
      <View className="screen confirmation-page">
        <View className="confirmation-panel">
          <View className="confirmation-page-title">还没有需要确认的内容</View>
          <View className="btn btn-primary" onClick={() => redirect('chat')}>返回问诊</View>
        </View>
      </View>
    );
  }

  const generate = (action: 'confirm' | 'correct') => {
    const correction = draft.trim();
    if (action === 'correct' && !correction) return;
    saveSession({
      ...session,
      generationRequest: action === 'confirm' ? { action } : { action, correction },
      report: null,
    });
    redirect('generating');
  };

  return (
    <View className="screen confirmation-page">
      <View className="confirmation-panel">
        <View className="confirmation-kicker">最后确认一下</View>
        <View className="confirmation-page-title">我有没有理解偏？</View>
        <View className="confirmation-summary">{session.confirmation}</View>

        {!correcting ? (
          <View className="confirmation-page-actions">
            <View className="btn btn-primary" onClick={() => generate('confirm')}>对，就是这个</View>
            <View className="btn btn-ghost" onClick={() => setCorrecting(true)}>不对，有点问题</View>
          </View>
        ) : (
          <View className="confirmation-page-form">
            <View className="confirmation-page-hint">哪里理解错了？补充一句就行。</View>
            <Input
              className="confirmation-page-input"
              value={draft}
              placeholder="例如：不是每天，是每周一两个小时"
              confirmType="send"
              focus
              onInput={(e) => setDraft(e.detail.value)}
              onConfirm={() => generate('correct')}
            />
            <View
              className={draft.trim() ? 'btn btn-primary' : 'btn btn-primary is-disabled'}
              onClick={() => draft.trim() && generate('correct')}
            >
              提交并生成报告
            </View>
          </View>
        )}
      </View>
    </View>
  );
}
