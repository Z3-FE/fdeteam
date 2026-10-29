import Taro from '@tarojs/taro';

export type PageId = 'home' | 'chat' | 'report' | 'success';

const MAP: Record<PageId, string> = {
  home: '/pages/landing/index',
  chat: '/pages/consult/index',
  report: '/pages/report/index',
  success: '/pages/success/index',
};

export function navigate(page: PageId): void {
  Taro.navigateTo({ url: MAP[page] });
}

export function redirect(page: PageId): void {
  Taro.redirectTo({ url: MAP[page] });
}

export function back(): void {
  const pages = Taro.getCurrentPages();
  if (pages.length > 1) {
    Taro.navigateBack();
  } else {
    Taro.redirectTo({ url: MAP.home });
  }
}
