import Taro, { useDidShow } from '@tarojs/taro';
import { useState } from 'react';
import { Input, Text, View } from '@tarojs/components';
import { IconSpark } from '../../components/icons';
import { HistoryEntry } from '../../components/HistoryEntry';
import {
  loadAccountPhone,
  loadSession,
  saveSession,
  type ConsultationSession,
  type Lead,
} from '../../data/consultation';
import { fetchLatestReport, postLead, submitReportFeedback } from '../../api/client';
import { MOCK_REPORT } from '../../data/mockReport';
import { navigate, relaunch } from '../../utils/nav';

type Accuracy = 'accurate' | 'needs_tweak' | null;

const CONTACT_TIME_OPTIONS = ['今天方便', '明天上午', '先加微信看方案'];

const pad2 = (n: number) => String(n).padStart(2, '0');

// 演示入口：没有真实报告时直接用 mock 数据展示，不写入本地存储
const loadReportSession = (): ConsultationSession => {
  const loaded = loadSession();
  return loaded.report ? loaded : { ...loaded, report: MOCK_REPORT, lead: null };
};

export default function Report() {
  const [session, setSession] = useState(loadReportSession);
  const [accuracy, setAccuracy] = useState<Accuracy>(() => (session.reportFeedback === 'accurate' ? 'accurate' : null));
  const [selected, setSelected] = useState<string[]>(() => {
    const first = session.report?.directions[0];
    return first ? [first.id] : [];
  });
  const [showFde, setShowFde] = useState(false);
  const [contact, setContact] = useState('');
  const [contactFocused, setContactFocused] = useState(false);
  const [contactTime, setContactTime] = useState(CONTACT_TIME_OPTIONS[0]);
  const [submitted, setSubmitted] = useState(false);

  // 每次显示都先读本地会话，再向后端取最后生成的那份报告；后端连不上时沿用本地
  useDidShow(() => {
    const apply = (next: ConsultationSession) =>
      setSession((prev) => {
        // 从历史报告切到另一份：页面状态按新报告重来，方向默认选中保存时选的那些
        if (next.conversationId !== prev.conversationId) {
          const saved = next.report?.directions.filter((d) => next.selectedDirections?.includes(d.title)) || [];
          const first = next.report?.directions[0];
          setSelected(saved.length > 0 ? saved.map((d) => d.id) : first ? [first.id] : []);
          setAccuracy(next.reportFeedback === 'accurate' ? 'accurate' : null);
          setShowFde(false);
          setSubmitted(false);
          setContact('');
          Taro.setNavigationBarTitle({ title: '诊断报告' });
          return next;
        }
        if (next.report && prev.report && next.report.createdAt !== prev.report.createdAt) {
          const first = next.report.directions[0];
          setSelected(first ? [first.id] : []);
        }
        if (next.reportFeedback === 'accurate') setAccuracy('accurate');
        return next;
      });
    apply(loadReportSession());
    const cid = loadSession().conversationId;
    if (!cid) return;
    fetchLatestReport(cid)
      .then((latest) => {
        const current = loadSession();
        if (!latest || current.conversationId !== cid) return;
        const synced: ConsultationSession = {
          ...current,
          report: latest.report,
          reportFeedback: latest.feedback,
          supplementNote: latest.supplements.join('；') || undefined,
          savedPhone: latest.savedPhone || current.savedPhone,
        };
        saveSession(synced);
        apply(synced);
      })
      .catch(() => {});
  });

  const report = session.report;
  if (!report) return null;

  const openQuestions = report.openQuestions || [];
  const supplementNote = (session.supplementNote || '').trim();
  const corrected = session.reportFeedback === 'corrected';
  const selectedTitles = report.directions.filter((d) => selected.includes(d.id)).map((d) => d.title);
  const canSubmit = contact.trim().length > 0;

  const toggleDirection = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const markAccurate = () => {
    setAccuracy('accurate');
    if (session.reportFeedback === 'accurate') return;
    const updated = { ...session, reportFeedback: 'accurate' as const };
    setSession(updated);
    saveSession(updated);
    if (session.conversationId) submitReportFeedback(session.conversationId, 'accurate').catch(() => {});
  };

  const openSupplement = () => {
    if (corrected) {
      Taro.showToast({ title: '报告已按补充修正过一次，其余可以直接和顾问说', icon: 'none' });
      return;
    }
    navigate('supplement');
  };

  // 诊断完成后不提供重新诊断，只能回首页；会话保留，报告还能再看
  const goHome = () => relaunch('home');

  // 从历史页点进来的直接返回，免得页面栈越叠越深；否则新开历史页
  const goHistory = () => {
    const pages = Taro.getCurrentPages();
    const prev = pages[pages.length - 2];
    if (prev && prev.route === 'pages/history/index') Taro.navigateBack();
    else navigate('history');
  };

  // 保存页要提交选中的方向，先写进本地会话
  const openSave = () => {
    if (session.savedPhone) {
      Taro.showToast({ title: `报告已保存到 ${session.savedPhone}`, icon: 'none' });
      return;
    }
    if (!session.conversationId) {
      Taro.showToast({ title: '这是示例报告，完成一次问诊后再保存', icon: 'none' });
      return;
    }
    saveSession({ ...loadSession(), selectedDirections: selectedTitles });
    navigate('save');
  };

  const toggleFde = (open: boolean) => {
    setShowFde(open);
    // 保存过报告就默认带出验证过的手机号，用户仍可改成微信号
    if (open && !contact.trim()) setContact(loadAccountPhone());
    Taro.setNavigationBarTitle({ title: open ? '联系 FDE 顾问' : '诊断报告' });
    Taro.pageScrollTo({ scrollTop: 0, duration: 0 });
  };

  const submitFde = () => {
    const value = contact.trim();
    if (!value) return;
    // 后端只收一个联系方式字段：11 位手机号记为 sms，其余按微信号处理
    const channel: Lead['channel'] = /^1\d{10}$/.test(value) ? 'sms' : 'wechat';
    if (session.conversationId) postLead(session.conversationId, channel, value).catch(() => {});
    const updated = { ...session, lead: { channel, phone: value, time: contactTime, createdAt: Date.now() } };
    setSession(updated);
    if (session.conversationId) saveSession(updated);
    setSubmitted(true);
  };

  if (showFde) {
    return (
      <View className="screen report-page">
        <View className="fde-scroll">
          {submitted ? (
            <View className="fde-success-block">
              <View className="fde-success-mark">✓</View>
              <View className="fde-success-title">已为你匹配 FDE 顾问</View>
              <View className="fde-success-desc">
                顾问已收到你的初步诊断摘要与联系方式（{contact.trim()}），将在 2 小时内按「{contactTime}」通过微信或电话与你对齐定制方案。
              </View>
              <View className="fde-context-card">
                <View className="fde-context-label">已附带的诊断摘要</View>
                <View className="fde-context-line">核心痛点：{report.painPoint}</View>
                <View className="fde-context-line">
                  关注方向：{selectedTitles.length > 0 ? selectedTitles.join('、') : '由顾问协助评估'}
                </View>
                {accuracy && (
                  <View className="fde-context-line">
                    准确度反馈：{accuracy === 'accurate' ? '分析准确' : '有细节待调整'}
                  </View>
                )}
              </View>
            </View>
          ) : (
            <View className="fde-form">
              <View className="fde-kicker">1 对 1 定制方案沟通</View>
              <View className="fde-title">联系 FDE 顾问</View>
              <View className="fde-subtitle">
                不用从头复述背景，这份初步诊断报告和待确认问题会直接同步给顾问，沟通聚焦在怎么落地、做多久、大概投入多少。
              </View>

              <View className="fde-context-card">
                <View className="fde-context-label">将同步给顾问的诊断结论</View>
                <View className="fde-context-line">问题：{report.painPoint}</View>
                <View className="fde-context-line">
                  代价：{report.costValue} {report.costUnit}
                  {report.costNote ? `（${report.costNote}）` : ''}
                </View>
                <View className="fde-context-line">
                  意向方向：{selectedTitles.length > 0 ? selectedTitles.join('、') : '未指定（由顾问推荐）'}
                </View>
                {!!supplementNote && <View className="fde-context-line">补充：{supplementNote}</View>}
              </View>

              <View className="fde-form-group">
                <View className="fde-form-label">你的微信号或手机号</View>
                <View className={`fde-input-box ${contactFocused ? 'is-focused' : ''}`}>
                  <Input
                    className="fde-input-field"
                    value={contact}
                    maxlength={40}
                    placeholder="输入微信号或手机号，方便顾问联系"
                    placeholderClass="fde-input-placeholder"
                    confirmType="done"
                    onFocus={() => setContactFocused(true)}
                    onBlur={() => setContactFocused(false)}
                    onInput={(e) => setContact(e.detail.value)}
                    onConfirm={submitFde}
                  />
                </View>
              </View>

              <View className="fde-form-group">
                <View className="fde-form-label">方便沟通的时间</View>
                <View className="picks">
                  {CONTACT_TIME_OPTIONS.map((opt) => (
                    <View
                      key={opt}
                      className={`pick ${contactTime === opt ? 'is-picked' : ''}`}
                      hoverClass="is-tap"
                      hoverStayTime={60}
                      onClick={() => setContactTime(opt)}
                    >
                      {contactTime === opt && <Text className="pick-check">✓</Text>}
                      {opt}
                    </View>
                  ))}
                </View>
              </View>
            </View>
          )}
        </View>

        <View className="fde-footer">
          {submitted ? (
            <View className="fde-submit is-active" hoverClass="is-tap" hoverStayTime={60} onClick={() => toggleFde(false)}>
              返回诊断报告
            </View>
          ) : (
            <>
              <View
                className={`fde-submit ${canSubmit ? 'is-active' : ''}`}
                hoverClass={canSubmit ? 'is-tap' : 'none'}
                hoverStayTime={60}
                onClick={submitFde}
              >
                确认发送诊断摘要并预约顾问
              </View>
              <View className="fde-back" hoverClass="is-tap" hoverStayTime={60} onClick={() => toggleFde(false)}>
                返回报告继续查看
              </View>
            </>
          )}
        </View>
      </View>
    );
  }

  return (
    <View className="screen report-page">
      <View className="report-scroll">
        <View className="report-top">
          <View className="report-kicker">
            <Text>{report.sceneLabel}</Text>
            <Text className="report-kicker-dot">·</Text>
            <Text>初步诊断报告</Text>
          </View>
          <HistoryEntry />
        </View>
        <View className="report-headline">{report.painPoint}</View>
        {!!report.painQuote && (
          <View className="report-quote-box">
            <Text className="report-quote-text">“{report.painQuote}”</Text>
          </View>
        )}

        <View className="report-cost-block">
          <View className="report-cost-label">预估消耗精力</View>
          <View className="report-cost-metric">
            <Text className="report-cost-value">{report.costValue}</Text>
            <Text className="report-cost-unit">{report.costUnit}</Text>
          </View>
          {!!report.costNote && <View className="report-cost-note">{report.costNote}</View>}
        </View>

        <View className="report-verify-box">
          {corrected ? (
            <>
              <View className="report-verify-prompt">已按你补充的背景更新报告</View>
              <View className="report-verify-feedback">其余还需要调整的细节，可以在沟通时直接告诉顾问。</View>
            </>
          ) : (
            <>
              <View className="report-verify-prompt">AI 对核心问题与代价的判断准确吗？</View>
              <View className="picks report-verify-actions">
                <View
                  className={`pick ${accuracy === 'accurate' ? 'is-picked' : ''}`}
                  hoverClass="is-tap"
                  hoverStayTime={60}
                  onClick={markAccurate}
                >
                  {accuracy === 'accurate' && <Text className="pick-check">✓</Text>}
                  准确，切中问题
                </View>
                <View
                  className={`pick ${accuracy === 'needs_tweak' ? 'is-picked' : ''}`}
                  hoverClass="is-tap"
                  hoverStayTime={60}
                  onClick={() => setAccuracy('needs_tweak')}
                >
                  {accuracy === 'needs_tweak' && <Text className="pick-check">✓</Text>}
                  基本对，有些偏差
                </View>
              </View>
              {accuracy === 'accurate' && (
                <View className="report-verify-feedback">已确认分析贴合实际，下面为你对比可落地的定制方向。</View>
              )}
              {accuracy === 'needs_tweak' && (
                <View className="report-verify-feedback">
                  可在沟通时直接告诉顾问哪里需要调整，或
                  <Text className="report-verify-link" onClick={openSupplement}>去补充修正细节 →</Text>
                </View>
              )}
            </>
          )}
        </View>

        {!!supplementNote && (
          <View className="report-block">
            <View className="report-section-label">你补充的背景</View>
            <View className="report-supplement-text">{supplementNote}</View>
          </View>
        )}

        <View className="report-block">
          <View className="report-section-header">
            <Text className="report-section-label">可行的定制解决方向</Text>
            <Text className="report-section-hint">点击勾选想聊的方向</Text>
          </View>
          {report.directions.map((dir, i) => {
            const isSelected = selected.includes(dir.id);
            return (
              <View
                key={dir.id}
                className={`report-direction-card ${isSelected ? 'is-selected' : ''}`}
                onClick={() => toggleDirection(dir.id)}
              >
                <View className="report-direction-head">
                  <View className="report-direction-title-wrap">
                    <Text className="report-direction-index">{pad2(i + 1)}</Text>
                    <Text className="report-direction-title">{dir.title}</Text>
                  </View>
                  <Text className={`report-direction-conf ${dir.confidence === '高' ? 'is-high' : ''}`}>
                    匹配度 · {dir.confidence}
                  </Text>
                </View>
                <View className="report-direction-summary">{dir.summary}</View>

                {dir.causes.length > 0 && (
                  <View className="report-sub-group">
                    <View className="report-sub-label">针对根因</View>
                    {dir.causes.map((cause) => (
                      <View className="report-list-item" key={cause}>
                        <Text className="report-list-dot">·</Text>
                        <Text className="report-list-text">{cause}</Text>
                      </View>
                    ))}
                  </View>
                )}

                {dir.actions.length > 0 && (
                  <View className="report-sub-group">
                    <View className="report-sub-label">怎么落地</View>
                    {dir.actions.map((action, j) => (
                      <View className="report-action-row" key={action}>
                        <Text className="report-action-index">{pad2(j + 1)}</Text>
                        <Text className="report-action-text">{action}</Text>
                      </View>
                    ))}
                  </View>
                )}

                <View className="report-direction-pick">
                  <Text className={`report-pick-text ${isSelected ? 'is-active' : ''}`}>
                    {isSelected ? '✓ 已选为与顾问重点讨论的方向' : '点击选择此方向'}
                  </Text>
                </View>
              </View>
            );
          })}
        </View>

        {openQuestions.length > 0 && (
          <View className="report-block">
            <View className="report-section-label">和 FDE 顾问沟通前，还需确认</View>
            {openQuestions.map((q, i) => (
              <View className="report-question-row" key={q}>
                <Text className="report-question-index">{pad2(i + 1)}</Text>
                <Text className="report-question-text">{q}</Text>
              </View>
            ))}
          </View>
        )}

        <View className="report-fde-handoff">
          <View className="report-fde-title">下一步：找 FDE 顾问评估定制开发</View>
          <View className="report-fde-desc">
            这份初步诊断能帮你对齐问题全貌；具体怎么接进现有 CRM 和微信群、大概多少开发周期，点击下方即可带着诊断记录直接与 FDE 顾问沟通。
          </View>
        </View>
      </View>

      <View className="report-footer">
        <View className="report-footer-actions">
          <View
            className={`report-save-btn ${session.savedPhone ? 'is-saved' : ''}`}
            hoverClass="is-tap"
            hoverStayTime={60}
            onClick={openSave}
          >
            <Text className="report-save-icon">{session.savedPhone ? '✓' : '⌑'}</Text>
            {session.savedPhone ? '已保存' : '保存报告'}
          </View>
          <View className="btn land-cta read-cta report-cta" onClick={() => toggleFde(true)}>
            <View className="land-cta-glow" />
            <View className="land-cta-beam" />
            <View className="land-cta-inner" />
            <View className="land-cta-label">
              <IconSpark />
              联系 FDE 顾问
            </View>
          </View>
        </View>
        <View className="report-footer-links">
          <Text className="report-footer-link" onClick={goHistory}>返回历史报告</Text>
          {/* 报告只能补充一次，用过后不再显示入口 */}
          {!corrected && (
            <>
              <Text className="report-footer-sep">·</Text>
              <Text className="report-footer-link" onClick={openSupplement}>补充信息</Text>
            </>
          )}
          <Text className="report-footer-sep">·</Text>
          <Text className="report-footer-link" onClick={goHome}>返回首页</Text>
        </View>
      </View>
    </View>
  );
}
