import Taro from '@tarojs/taro';
import { useEffect, useRef, useState } from 'react';
import { Text, View } from '@tarojs/components';
import { Sprite } from '../../components/Sprite';
import { loadSession } from '../../data/consultation';

const TITLE = ['正', '在', '认', '真', '整', '理', '.', '.', '.'];
const DURATION = 7000;

export default function Generating() {
  const [progress, setProgress] = useState(0);
  const completedRef = useRef(false);

  useEffect(() => {
    const startedAt = Date.now();
    let redirectTimer: ReturnType<typeof setTimeout> | null = null;
    const timer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const visualProgress = Math.min(99, Math.floor((elapsed / DURATION) * 100));
      setProgress(visualProgress);

      if (elapsed >= DURATION && loadSession().report && !completedRef.current) {
        completedRef.current = true;
        setProgress(100);
        clearInterval(timer);
        redirectTimer = setTimeout(() => Taro.redirectTo({ url: '/pages/report/index' }), 450);
      }
    }, 100);
    return () => {
      clearInterval(timer);
      if (redirectTimer) clearTimeout(redirectTimer);
    };
  }, []);

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
      </View>
    </View>
  );
}
