# 问题梳理 · 微信小程序（Taro）

用 Taro(React+TS) 把 H5 版重构成微信小程序；同一套代码也能编译 H5。

## 安装 & 构建
```bash
cd miniapp
npm install
npm run dev:weapp     # 开发：持续编译到 dist/，用微信开发者工具打开本目录
npm run build:weapp   # 打包
npm run dev:h5        # 也能编 H5
```

## 用微信开发者工具打开
1. 微信开发者工具 → 导入项目 → 选择 `miniapp` 目录；
2. AppID：先用「测试号」或你自己的 AppID（`project.config.json` 里现在是占位 `touristappid`）；
3. 开发阶段，右上角「详情 → 本地设置」勾上 **不校验合法域名**，这样能直连本机后端 `http://127.0.0.1:8000`。

## 连后端
- 后端地址在 `src/api/client.ts` 的 `API_BASE`，默认 `http://127.0.0.1:8000/api`。
- 先把后端跑起来（见 `../backend/README.md`，可 MOCK，也可填 key 用真实 DeepSeek）。
- **上线前**：把 `API_BASE` 改成你**备案后的 HTTPS 域名**，并在小程序后台「开发管理 → 服务器域名」里把它加进 **request 合法域名**白名单。

## 页面与结构
- `src/app.config.ts`  页面路由（landing / consult / report / success）
- `src/pages/*`         四个页面
- `src/components/LeadSheet.tsx`  留资底部弹窗
- `src/api/client.ts`   Taro.request 调后端
- `src/data/consultation.ts`  会话数据 + Taro 本地存储
- `src/utils/nav.ts`    页面跳转
- `src/app.css`         样式（从 H5 版移植，已补小程序适配）

## 这次做了哪些适配（H5 → 小程序）
- 组件：div/span/p/h → `View/Text`；input → `Input`；滚动区 → `ScrollView`；
- 存储：localStorage → `Taro.getStorageSync`；网络：fetch → `Taro.request`；
- 路由：hash → Taro 页面跳转。

## 还需你在开发者工具里过一遍 / 后续优化
- **图标**：现在是 emoji/字符占位（小程序不支持内联 SVG）。要精致图标，建议接 **iconfont**（彩色/线性图标）替换 `src/components/icons.tsx`。
- **微信一键手机号**：目前是「模拟授权」占位。真要用，需把微信授权按钮 `Button open-type="getPhoneNumber"` + 后端解密手机号接上（P0 先用短信/模拟即可）。
- **样式细节**：布局/卡片/配色已移植；个别字号或间距在真机上可能要微调（px→rpx 的 `designWidth=375`，不合适可在 `config/index.js` 调）。
- Landing 的插画用一个简化的渐变气泡代替了原 SVG。
