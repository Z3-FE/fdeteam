import Taro, { useDidShow } from '@tarojs/taro';
import { useRef, useState } from 'react';
import { Text, View } from '@tarojs/components';
import { IconCheck, IconSpark } from '../../components/icons';
import { Sprite } from '../../components/Sprite';
import { HistoryEntry } from '../../components/HistoryEntry';
import { resetSession } from '../../data/consultation';
import { navigate } from '../../utils/nav';

const TAGS = ['免注册', '3 分钟出结果', '不收费'];
// 点击后先播完动画再跳转
const LAUNCH_DELAY = 420;

interface Ripple {
  id: number;
  x: number;
  y: number;
}

export default function Landing() {
  const [pressed, setPressed] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [pulse, setPulse] = useState(0);
  const [ripples, setRipples] = useState<Ripple[]>([]);
  const busyRef = useRef(false);
  const rippleId = useRef(0);

  // 从问诊页返回时恢复按钮
  useDidShow(() => {
    busyRef.current = false;
    setLaunching(false);
    setPressed(false);
  });

  const addRipple = (clientX: number, clientY: number) => {
    Taro.createSelectorQuery()
      .select('#land-cta')
      .boundingClientRect((rect) => {
        const r = Array.isArray(rect) ? rect[0] : rect;
        const id = ++rippleId.current;
        const x = r ? clientX - r.left : 0;
        const y = r ? clientY - r.top : 0;
        setRipples((list) => [...list, { id, x, y }]);
        setTimeout(() => setRipples((list) => list.filter((item) => item.id !== id)), 700);
      })
      .exec();
  };

  const onTouchStart = (e: any) => {
    if (busyRef.current) return;
    setPressed(true);
    const t = e.touches && e.touches[0];
    if (t) addRipple(t.clientX, t.clientY);
  };

  const launch = () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setPressed(false);
    setLaunching(true);
    setPulse((n) => n + 1);
    // 首页只负责开一次新的问诊，看以前的报告走右上角"历史报告"
    setTimeout(() => {
      resetSession();
      navigate('chat');
    }, LAUNCH_DELAY);
  };

  const ctaClass = `btn land-cta${pressed ? ' is-pressed' : ''}${launching ? ' is-launching' : ''}`;

  return (
    <View className="screen landing">
      <View className="land-top">
        <HistoryEntry />
      </View>
      <View className="hero-stage">
        <View className="hero-bubble">
          <Text className="hero-bubble-text">嗨，最近生意上哪件事最让你头疼？</Text>
        </View>
        <Sprite tone="mono" pulse={pulse} />
      </View>

      <View className="land-tags">
        {TAGS.map((text) => (
          <View className="land-tag" key={text}>
            <IconCheck />
            {text}
          </View>
        ))}
      </View>

      <View className="land-cta-wrap">
        <View
          id="land-cta"
          className={ctaClass}
          onTouchStart={onTouchStart}
          onTouchEnd={() => setPressed(false)}
          onTouchCancel={() => setPressed(false)}
          onClick={launch}
        >
          <View className="land-cta-glow" />
          <View className="land-cta-beam" />
          <View className="land-cta-trace" />
          <View className="land-cta-inner">
            {ripples.map((r) => (
              <View className="land-cta-ripple" key={r.id} style={{ left: `${r.x}px`, top: `${r.y}px` }} />
            ))}
          </View>
          <View className="land-cta-label">
            <IconSpark />
            说说我的困扰
          </View>
        </View>
        <View className="land-trust">
          <View className="land-trust-mark" />
          不推销，不打扰，只帮你理清思路
        </View>
      </View>
    </View>
  );
}
