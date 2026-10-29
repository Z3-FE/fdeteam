import { Text, View } from '@tarojs/components';
import { IconCheck, IconHome, IconRestart } from '../../components/icons';
import { resetSession } from '../../data/consultation';
import { navigate, redirect } from '../../utils/nav';

export default function Success() {
  const restart = () => {
    resetSession();
    redirect('chat');
  };

  return (
    <View className="screen success">
      <View className="success-inner">
        <View className="success-badge">
          <IconCheck />
        </View>
        <View className="success-title">收到，我们会尽快安排人跟你联系。</View>
        <View className="success-text">这份诊断已帮你存好，随时能回来看。</View>

        <View className="success-notes">
          <View className="success-note">
            <View className="success-note-dot" />
            <Text>顾问会先了解情况，不会一上来就报价</Text>
          </View>
          <View className="success-note">
            <View className="success-note-dot" />
            <Text>如果你暂时不想推进，放着就行，不会有催促</Text>
          </View>
        </View>

        <View className="success-actions">
          <View className="btn btn-primary" onClick={restart}>
            <IconRestart />
            再诊断一个问题
          </View>
          <View className="btn btn-ghost" onClick={() => redirect('home')}>
            <IconHome />
            返回首页
          </View>
        </View>

        <View className="success-foot">报告存在这台设备上，换设备看不到。</View>
      </View>
    </View>
  );
}
