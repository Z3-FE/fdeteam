import Taro from '@tarojs/taro';
import { useState } from 'react';
import { Text, Textarea, View } from '@tarojs/components';
import { loadSession, saveSession } from '../../data/consultation';
import { IconSpark } from '../../components/icons';
import { back, redirect } from '../../utils/nav';

// 问诊结束后"再补充一下"：补充内容走 correctUnderstanding，一并写进报告
const SUPPLEMENT_TAGS = ['团队约 10–30 人', '用过飞书或钉钉文档', '希望两周内见效', '目前没有专职培训岗'];

const tokensOf = (text: string) =>
  text
    .split('、')
    .map((t) => t.trim())
    .filter(Boolean);

export default function Supplement() {
  const [note, setNote] = useState('');
  const [focused, setFocused] = useState(false);
  const picked = SUPPLEMENT_TAGS.filter((t) => tokensOf(note).includes(t));
  const canSubmit = note.trim().length > 0;
  const [fromReport] = useState(() => loadSession().report !== null);

  // 标签和输入框同步：选中追加（用"、"连接），取消时从输入框里去掉
  const toggleTag = (tag: string) => {
    const tokens = tokensOf(note);
    if (tokens.includes(tag)) setNote(tokens.filter((t) => t !== tag).join('、'));
    else setNote(note.trim() ? `${note.trim()}、${tag}` : tag);
  };

  const submit = () => {
    const correction = note.trim();
    const session = loadSession();
    if (!correction || !session.conversationId) return;
    // 已有报告：从报告页过来补充，修正当前报告（后端只允许一次）
    if (session.report) {
      if (session.reportFeedback === 'corrected') {
        Taro.showToast({ title: '报告已按补充修正过一次，其余可以直接和顾问说', icon: 'none' });
        return;
      }
      // 问诊阶段已补充过的话，报告里两次补充都展示
      const merged = session.supplementNote ? `${session.supplementNote}；${correction}` : correction;
      saveSession({ ...session, generationRequest: { action: 'revise', correction }, supplementNote: merged });
    } else {
      saveSession({ ...session, generationRequest: { action: 'correct', correction }, supplementNote: correction });
    }
    redirect('generating');
  };

  return (
    <View className="screen supplement">
      <View className="supplement-body">
        <View className="supplement-title">还有什么想补充的背景？</View>
        <View className="supplement-sub">比如团队人数、已经试过的办法，或者你最在意的限制条件，会一并写进报告里。</View>

        <View className={`supplement-box ${focused ? 'is-focused' : ''}`}>
          <Textarea
            className="supplement-input"
            value={note}
            maxlength={500}
            placeholder="用大白话写下你想补充的内容…"
            placeholderClass="supplement-placeholder"
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onInput={(e) => setNote(e.detail.value)}
          />
        </View>

        <View className="picks supplement-tags">
          {SUPPLEMENT_TAGS.map((tag) => (
            <View
              key={tag}
              className={`pick ${picked.includes(tag) ? 'is-picked' : ''}`}
              hoverClass="is-tap"
              hoverStayTime={60}
              onClick={() => toggleTag(tag)}
            >
              {picked.includes(tag) && <Text className="pick-check">✓</Text>}
              {tag}
            </View>
          ))}
        </View>
      </View>

      <View className="supplement-footer">
        <View
          className={`supplement-submit ${canSubmit ? 'is-active' : ''}`}
          hoverClass={canSubmit ? 'is-tap' : 'none'}
          hoverStayTime={60}
          onClick={submit}
        >
          <IconSpark />
          <Text className="supplement-submit-text">{fromReport ? '提交并更新诊断报告' : '提交并生成诊断报告'}</Text>
        </View>
        <View className="supplement-back" hoverClass="is-tap" hoverStayTime={60} onClick={back}>
          {fromReport ? '返回诊断报告' : '返回问诊'}
        </View>
      </View>
    </View>
  );
}
