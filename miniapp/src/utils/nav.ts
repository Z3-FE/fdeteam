import Taro from '@tarojs/taro';

export type PageId = 'home' | 'chat' | 'confirmation' | 'supplement' | 'report' | 'generating' | 'success' | 'save' | 'history';

const MAP: Record<PageId, string> = {
  home: '/pages/landing/index',
  chat: '/pages/consult/index',
  confirmation: '/pages/confirmation/index',
  supplement: '/pages/supplement/index',
  report: '/pages/report/index',
  generating: '/pages/generating/index',
  success: '/pages/success/index',
  save: '/pages/save/index',
  history: '/pages/history/index',
};

export function navigate(page: PageId): void {
  Taro.navigateTo({ url: MAP[page] });
}

export function redirect(page: PageId): void {
  Taro.redirectTo({ url: MAP[page] });
}

export function relaunch(page: PageId): void {
  Taro.reLaunch({ url: MAP[page] });
}

export function back(): void {
  const pages = Taro.getCurrentPages();
  if (pages.length > 1) {
    Taro.navigateBack();
  } else {
    Taro.redirectTo({ url: MAP.home });
  }
}
