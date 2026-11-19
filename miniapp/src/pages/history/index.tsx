import Taro, { useDidShow } from '@tarojs/taro';
import { useRef, useState } from 'react';
import { Text, View } from '@tarojs/components';
import { IconSpark } from '../../components/icons';
import { createSession, loadSession, resetSession, saveSession } from '../../data/consultation';
import { deleteSavedReport, fetchSavedReports, type SavedReport } from '../../api/client';
import { navigate, relaunch } from '../../utils/nav';

const ALL = '全部';
// 和首页按钮一样：先播完点击动画再跳转
const LAUNCH_DELAY = 420;

const pad2 = (n: number) => String(n).padStart(2, '0');

// 今年的只写月日和时间，往年的带上年份
function formatSavedAt(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '';
  const time = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  const day = `${d.getMonth() + 1}月${d.getDate()}日`;
  return d.getFullYear() === new Date().getFullYear() ? `${day} ${time}` : `${d.getFullYear()}年${day} ${time}`;
}

// 历史报告：登录用户保存过的每份报告，点开回到报告页查看
export default function History() {
  const [items, setItems] = useState<SavedReport[]>([]);
  const [accountPhone, setAccountPhone] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [scene, setScene] = useState(ALL);
  const [activeId, setActiveId] = useState<string | null>(() => loadSession().conversationId);
  const [pressed, setPressed] = useState(false);
  const [launching, setLaunching] = useState(false);
  const busyRef = useRef(false);

  const load = () => {
    busyRef.current = false;
    setLaunching(false);
    setPressed(false);
    setActiveId(loadSession().conversationId);
    fetchSavedReports()
      .then((data) => {
        setItems(data.items);
        setAccountPhone(data.accountPhone);
        setFailed(false);
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  };

  useDidShow(load);

  const scenes = [ALL, ...Array.from(new Set(items.map((i) => i.report.sceneLabel).filter(Boolean)))];
  const currentScene = scenes.includes(scene) ? scene : ALL;
  const visible = currentScene === ALL ? items : items.filter((i) => i.report.sceneLabel === currentScene);

  // 本地只存一次问诊：打开历史报告就把它换成那份报告，报告页再按 conversationId 向后端同步补充和反馈
  // 从报告页进来的直接返回，报告页显示时会按本地会话刷新；否则新开报告页。免得页面栈越叠越深
  const showReport = () => {
    const pages = Taro.getCurrentPages();
    const prev = pages[pages.length - 2];
    if (prev && prev.route === 'pages/report/index') Taro.navigateBack();
    else navigate('report');
  };

  const open = (item: SavedReport) => {
    const local = loadSession();
    if (item.conversationId === local.conversationId) {
      showReport();
      return;
    }
    // 本机有一次还没出报告的问诊时，切过去会丢掉它，先确认
    if (!local.report && local.answers.length > 0) {
      Taro.showModal({
        title: '查看这份报告',
        content: '当前还有一次没完成的问诊，切换后它不会保留，确定查看吗？',
        confirmText: '查看',
        confirmColor: '#111111',
        success: (res) => res.confirm && switchTo(item),
      });
      return;
    }
    switchTo(item);
  };

  const switchTo = (item: SavedReport) => {
    saveSession({
      ...createSession(),
      conversationId: item.conversationId,
      report: item.report,
      reportFeedback: item.feedback,
      savedPhone: item.savedPhone,
      selectedDirections: item.directions,
    });
    showReport();
  };

  const remove = (item: SavedReport) => {
    Taro.showModal({
      title: '删除这份报告',
      content: '删除后不再出现在历史报告里，顾问那边已收到的诊断摘要不受影响。',
      confirmText: '删除',
      confirmColor: '#111111',
      success: (res) => {
        if (!res.confirm) return;
        deleteSavedReport(item.conversationId)
          .then(() => {
            setItems((list) => list.filter((i) => i.conversationId !== item.conversationId));
            Taro.showToast({ title: '已删除', icon: 'none' });
          })
          .catch(() => Taro.showToast({ title: '删除失败，请稍后再试', icon: 'none' }));
      },
    });
  };

  const startNew = () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setPressed(false);
    setLaunching(true);
    setTimeout(() => {
      resetSession();
      navigate('chat');
    }, LAUNCH_DELAY);
  };

  const ctaClass = `btn land-cta history-cta${pressed ? ' is-pressed' : ''}${launching ? ' is-launching' : ''}`;

  return (
    <View className="screen report-page history-page">
      <View className="history-scroll">
        <View className="history-summary-bar">
          <View className="history-count">
            <Text className="history-count-num">{loading ? '–' : items.length}</Text>
            <Text className="history-count-label">份已保存报告</Text>
          </View>
          <Text className="history-account-tag">{accountPhone ? `账号 ${accountPhone}` : '未绑定手机号'}</Text>
        </View>

        {scenes.length > 2 && (
          <View className="picks history-filter">
            {scenes.map((label) => (
              <View
                key={label}
                className={`pick ${currentScene === label ? 'is-picked' : ''}`}
                hoverClass="is-tap"
                hoverStayTime={60}
                onClick={() => setScene(label)}
              >
                {label}
              </View>
            ))}
          </View>
        )}

        {failed && items.length === 0 ? (
          <View className="history-empty">
            <View className="history-empty-title">历史报告加载失败</View>
            <View className="history-empty-desc">网络或服务暂时不可用，请稍后再试。</View>
            <View className="history-retry" hoverClass="is-tap" hoverStayTime={60} onClick={load}>
              重新加载
            </View>
          </View>
        ) : !loading && items.length === 0 ? (
          <View className="history-empty">
            <View className="history-empty-title">暂无已保存的诊断报告</View>
            <View className="history-empty-desc">
              完成 AI 业务问诊并在报告页点击「保存报告」后，每份诊断结论与定制方案都会沉淀在这里，方便随时回看与跟进。
            </View>
          </View>
        ) : (
          <View className="history-list">
            {visible.map((item) => {
              const { report } = item;
              const active = item.conversationId === activeId;
              const direction = item.directions[0] || report.directions[0]?.title;
              return (
                <View
                  key={item.conversationId}
                  className={`history-card ${active ? 'history-card-active' : ''}`}
                  onClick={() => open(item)}
                >
                  <View className="history-card-top">
                    <View className="history-card-meta">
                      <Text className="history-card-scene">{report.sceneLabel}</Text>
                      <Text className="history-card-dot">·</Text>
                      <Text className="history-card-time">{formatSavedAt(item.savedAt)}</Text>
                    </View>
                    <Text className={`history-status ${item.status === 'consulted' ? 'is-consulted' : ''}`}>
                      {item.status === 'consulted' ? '已约 FDE 顾问' : '已保存'}
                    </Text>
                  </View>
                  <View className="history-card-title">{report.painPoint}</View>
                  {!!report.painQuote && <View className="history-card-quote">“{report.painQuote}”</View>}
                  <View className="history-card-metrics">
                    {!!report.costValue && (
                      <Text className="history-cost-chip">
                        {report.costValue} {report.costUnit}
                      </Text>
                    )}
                    {!!direction && <Text className="history-dir-text">方向：{direction}</Text>}
                  </View>
                  <View className="history-card-foot">
                    <Text
                      className="history-delete"
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(item);
                      }}
                    >
                      删除
                    </Text>
                    <Text className="history-open">{active ? '当前正在查看 →' : '查看报告 →'}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </View>

      <View className="fde-footer history-footer">
        <View
          className={ctaClass}
          onTouchStart={() => setPressed(true)}
          onTouchEnd={() => setPressed(false)}
          onTouchCancel={() => setPressed(false)}
          onClick={startNew}
        >
          <View className="land-cta-glow" />
          <View className="land-cta-beam" />
          <View className="land-cta-trace" />
          <View className="land-cta-inner" />
          <View className="land-cta-label">
            <IconSpark />
            发起新的业务问诊
          </View>
        </View>
        <View className="fde-back" hoverClass="is-tap" hoverStayTime={60} onClick={() => relaunch('home')}>
          返回首页
        </View>
      </View>
    </View>
  );
}
