import { PropsWithChildren } from 'react';
import { useLaunch } from '@tarojs/taro';
import { ensureLogin } from './api/client';
import './app.css';

function App({ children }: PropsWithChildren) {
  // 启动就先登录，首页查报告、问诊发消息时直接带上登录态
  useLaunch(() => {
    ensureLogin();
  });
  return children;
}

export default App;
