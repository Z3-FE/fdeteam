import { Text, View } from '@tarojs/components';
import { IconChat, IconClock, IconShield, IconUserBadge, IconYuan } from '../../components/icons';
import { navigate } from '../../utils/nav';

const FEATURES = [
  { Icon: IconYuan, title: '完全免费', text: '0 费用，无隐藏消费' },
  { Icon: IconUserBadge, title: '无需注册', text: '点开即用，保护隐私' },
  { Icon: IconClock, title: '快速诊断', text: '2~5 分钟，清晰方向' },
];

export default function Landing() {
  return (
    <View className="screen landing">
      <View className="land-top">
        <View className="land-brand-mark">
          <IconChat />
        </View>
        <View>
          <View className="land-brand-name">经营问诊</View>
          <View className="land-brand-sub">免费 AI 经营问诊工具</View>
        </View>
      </View>

      <View className="hero">
        <View className="hero-title">
          你公司最头疼的那件事，先<Text className="accent">免费</Text>理清楚
        </View>
        <View className="hero-sub">像聊天一样说说你的困扰，我帮你诊断问题出在哪、能怎么解决</View>
        <View className="hero-stage">
          <View
            style={{
              width: '120px',
              height: '120px',
              borderRadius: '50%',
              background: 'linear-gradient(160deg,#ffa287,#ff7a59)',
              boxShadow: '0 12px 30px rgba(232,92,63,0.28)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '14px 0 6px',
            }}
          >
            <Text style={{ fontSize: '46px' }}>💬</Text>
          </View>
        </View>
      </View>

      <View className="land-features">
        {FEATURES.map((item) => {
          const Ic = item.Icon;
          return (
            <View className="land-feature" key={item.title}>
              <View className="feature-icon">
                <Ic />
              </View>
              <View>
                <View className="feature-title">{item.title}</View>
                <View className="feature-text">{item.text}</View>
              </View>
            </View>
          );
        })}
      </View>

      <View className="land-cta-wrap">
        <View className="btn btn-primary land-cta" onClick={() => navigate('chat')}>
          开始免费诊断
        </View>
        <View className="land-trust">
          <IconShield />
          不推销，不打扰，只帮你理清思路
        </View>
      </View>
    </View>
  );
}
