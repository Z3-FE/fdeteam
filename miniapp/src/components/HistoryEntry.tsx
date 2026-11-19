import { useDidShow } from '@tarojs/taro';
import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { fetchSavedReports } from '../api/client';
import { navigate } from '../utils/nav';

// "历史报告"入口：右上角的小圆角按钮，有保存过的报告时带上份数
export function HistoryEntry({ className = '' }: { className?: string }) {
  const [count, setCount] = useState(0);

  useDidShow(() => {
    fetchSavedReports()
      .then((data) => setCount(data.items.length))
      .catch(() => {});
  });

  return (
    <View
      className={`nav-history-btn ${className}`}
      hoverClass="is-tap"
      hoverStayTime={60}
      onClick={(e) => {
        e.stopPropagation();
        navigate('history');
      }}
    >
      <Text>历史报告</Text>
      {count > 0 && <Text className="nav-history-badge">{count}</Text>}
    </View>
  );
}
