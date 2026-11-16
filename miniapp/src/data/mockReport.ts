import type { DiagnosisReport } from './consultation';

// 调试用：报告页带 ?mock=1 时直接展示这份数据，不用先走一遍问诊
export const MOCK_REPORT: DiagnosisReport = {
  sceneId: 'mock',
  sceneLabel: '内部流程',
  painPoint: '销售频繁在微信群重复咨询 CRM 操作问题，占用产品经理大量时间',
  painQuote: '销售每天在微信群里问一堆重复的问题，把产品经理搞得很烦',
  costValue: '1~2',
  costUnit: '小时/天',
  costNote: '按每月 22 个工作日算，一个月大约 22~44 小时',
  directions: [
    {
      id: 'mock-1',
      title: 'CRM 智能问答机器人',
      confidence: '高',
      summary: '用 AI 问答技术做一个集成在微信群的机器人，自动回答销售关于 CRM 的常见操作问题',
      causes: ['销售嫌翻手册麻烦', '群里提问比查手册快'],
      actions: ['机器人自动识别销售在群里问的 CRM 问题，秒回操作指引', '覆盖每天 10~20 个高频重复问题，解放产品经理时间'],
    },
    {
      id: 'mock-2',
      title: 'CRM 操作短视频库',
      confidence: '中',
      summary: '把手册内容做成 30 秒短视频，通过小程序让销售随时点播查看',
      causes: ['文字手册查阅不便'],
      actions: ['每个 CRM 操作步骤拍成短视频，销售点击问题直接播放', '支持在微信群通过链接一键分享给提问的同事'],
    },
  ],
  openQuestions: ['现有 CRM 系统是否支持对接第三方机器人', '销售更接受文字指引还是视频演示'],
  createdAt: Date.now(),
};
