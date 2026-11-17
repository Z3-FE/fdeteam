import Taro from '@tarojs/taro';
import { useEffect, useRef, useState } from 'react';
import { Text, View } from '@tarojs/components';
import { Sprite } from '../../components/Sprite';
import { confirmUnderstanding, correctUnderstanding } from '../../api/client';
import { loadSession, saveSession } from '../../data/consultation';

const TITLE = ['正', '在', '认', '真', '整', '理', '.', '.', '.'];
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
    const request = session.generationRequest.action === 'confirm'
      ? confirmUnderstanding(session.conversationId)
      : correctUnderstanding(session.conversationId, session.generationRequest.correction || '');
    request.then((result) => {
      if (result.type !== 'report' || completedRef.current) throw new Error('report generation failed');
      completedRef.current = true;
      clearInterval(timer);
      saveSession({ ...session, report: result.report, confirmation: null, generationRequest: null, suggestions: [] });
      setProgress(100);
      setTimeout(() => Taro.redirectTo({ url: '/pages/report/index' }), 420);
    }).catch(() => {
      clearInterval(timer);
      setFailed(true);
    });
    return () => clearInterval(timer);
  }, [attempt]);

  return (
    <View className="screen generating">
      <View className="generating-main">
        <View className="generating-orb"><Sprite busy /></View>
        <View className="generating-title">
          {TITLE.map((char, index) => (
            <Text className="generating-title-char" style={{ animationDelay: `${index * 0.11}s` }} key={`${char}-${index}`}>{char}</Text>
          ))}
        </View>
        <View className={`generating-percent ${progress === 100 ? 'is-complete' : ''}`}>{progress}%</View>
        {failed && (
          <View className="generating-retry">
            <View className="generating-retry-text">生成时网络开小差了</View>
            <View className="btn btn-primary" onClick={() => { setFailed(false); setProgress(0); setAttempt((n) => n + 1); }}>
              重新生成
            </View>
          </View>
        )}
      </View>
    </View>
  );
}
