import Taro from '@tarojs/taro';
import { useEffect, useRef, useState } from 'react';
import { View } from '@tarojs/components';
import { Vortex } from '../../components/Vortex';
import { confirmUnderstanding, correctUnderstanding, submitReportFeedback } from '../../api/client';
import type { DiagnosisReport } from '../../data/consultation';
import { loadSession, saveSession } from '../../data/consultation';

const DURATION = 7000;

export default function Generating() {
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const completedRef = useRef(false);

  useEffect(() => {
    const session = loadSession();
    if (!session.conversationId || !session.generationRequest) {
      Taro.redirectTo({ url: session.report ? '/pages/report/index' : '/pages/consult/index' });
      return;
    }
    completedRef.current = false;
    const startedAt = Date.now();
    const timer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      setProgress(Math.min(92, Math.floor((elapsed / DURATION) * 92)));
    }, 100);
    const { action, correction = '' } = session.generationRequest;
    const conversationId = session.conversationId;
    // revise：看完报告后补充，走报告纠错接口；其余是问诊结束后的确认/纠正
    const request: Promise<DiagnosisReport | null> = action === 'revise'
      ? submitReportFeedback(conversationId, 'correct', correction)
      : (action === 'confirm' ? confirmUnderstanding(conversationId) : correctUnderstanding(conversationId, correction))
        .then((result) => (result.type === 'report' ? result.report : null));
    request.then((report) => {
      if (!report || completedRef.current) throw new Error('report generation failed');
      completedRef.current = true;
      clearInterval(timer);
      saveSession({
        ...session,
        report,
        confirmation: null,
        generationRequest: null,
        suggestions: [],
        reportFeedback: action === 'revise' ? 'corrected' : session.reportFeedback,
      });
      setProgress(100);
      // revise 从报告页进来：退回原报告页（它在 useDidShow 里重新读会话），避免栈里叠两份报告
      const backToReport = action === 'revise' && Taro.getCurrentPages().length > 1;
      setTimeout(() => (backToReport ? Taro.navigateBack() : Taro.redirectTo({ url: '/pages/report/index' })), 420);
    }).catch(() => {
      clearInterval(timer);
      setFailed(true);
    });
    return () => clearInterval(timer);
  }, [attempt]);

  return (
    <View className="screen generating">
      <View className="generating-main">
        <View className="generating-orb"><Vortex progress={progress} /></View>
        {failed && (
          <View className="generating-retry">
            <View className="generating-retry-text">生成时网络开小差了</View>
            <View className="btn generating-retry-btn" hoverClass="is-tap" hoverStayTime={60} onClick={() => { setFailed(false); setProgress(0); setAttempt((n) => n + 1); }}>
              重新生成
            </View>
          </View>
        )}
      </View>
    </View>
  );
}
