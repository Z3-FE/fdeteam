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

export function AIAvatar({ size = 32 }: { size?: number }) {
  return (
    <View className="ai-avatar" style={{ width: `${size}px`, height: `${size}px`, fontSize: '13px' }}>
      <Text>AI</Text>
    </View>
  );
}
