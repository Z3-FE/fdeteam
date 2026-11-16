import { Text, View } from '@tarojs/components';
import { IconCheck, IconShield } from '../../components/icons';
import { Sprite } from '../../components/Sprite';
import { resetSession } from '../../data/consultation';
import { navigate } from '../../utils/nav';

const TAGS = ['免注册', '3 分钟出结果', '不收费'];

export default function Landing() {
  return (
    <View className="screen landing">
      <View className="hero">
        <View className="hero-title">
          经营难题，先<Text className="accent">免费</Text>理清楚
        </View>
        <View className="hero-sub">说说你的困扰，帮你找到问题和解法</View>
      </View>

      <View className="hero-stage">
        <View className="hero-bubble">嗨，最近生意上哪件事最让你头疼？</View>
        <Sprite />
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
        <View className="btn btn-primary land-cta" onClick={() => { resetSession(); navigate('chat'); }}>
          说说我的困扰
        </View>
        <View className="land-trust">
          <IconShield />
          不推销，不打扰，只帮你理清思路
        </View>
      </View>
    </View>
  );
}
