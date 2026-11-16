import { Text, View } from '@tarojs/components';

interface IconProps {
  width?: number;
  height?: number;
  className?: string;
}

function make(char: string) {
  return function Icon({ className }: IconProps) {
    return <Text className={`qb-icon ${className || ''}`}>{char}</Text>;
  };
}

export const IconBack = make('‹');
export const IconSend = make('➤');
export const IconLock = make('🔒');
export const IconCheck = make('✓');
export const IconShield = make('🛡');
export const IconSpark = make('✦');
export const IconArrow = make('→');
export const IconRestart = make('↻');
export const IconClock = make('⏱');
export const IconChat = make('💬');
export const IconYuan = make('¥');
export const IconUserBadge = make('👤');
export const IconWeChat = make('✚');
export const IconHome = make('⌂');

// 问诊页头像：落地页能量球的缩小版，思考时眼睛左右张望
export function AIAvatar({
  size = 32,
  active = false,
  thinking = false,
}: {
  size?: number;
  active?: boolean;
  thinking?: boolean;
}) {
  // 用 margin 而不是 gap 拉开两只眼睛，老版本基础库的 flex 不认 gap
  const eye = {
    width: `${Math.round(size * 0.12)}px`,
    height: `${Math.round(size * 0.22)}px`,
    margin: `0 ${Math.round(size * 0.09)}px`,
  };
  return (
    <View
      className={`ai-avatar ${active ? 'is-active' : ''} ${thinking ? 'is-thinking' : ''}`}
      style={{ width: `${size}px`, height: `${size}px` }}
    >
      <Text className="orb-eye" style={eye} />
      <Text className="orb-eye" style={eye} />
    </View>
  );
}
