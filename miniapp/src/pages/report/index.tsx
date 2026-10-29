import { useState } from 'react';
import { Text, View } from '@tarojs/components';
import { LeadSheet } from '../../components/LeadSheet';
import { IconArrow, IconBack, IconCheck, IconLock, IconRestart, IconShield, IconSpark } from '../../components/icons';
import { formatReportDate, loadSession, maskPhone, type Confidence, type Lead } from '../../data/consultation';
import { back, navigate, redirect } from '../../utils/nav';

const TAG_CLASS: Record<Confidence, string> = {
  高: 'tag tag-high',
  中: 'tag tag-mid',
  低: 'tag tag-low',
};

export default function Report() {
  const [session, setSession] = useState(() => loadSession());
  const [sheetOpen, setSheetOpen] = useState(false);
  const report = session.report;
  const lead: Lead | null = session.lead;

  if (!report) {
    return (
      <View className="screen report">
        <View className="report-inner">
          <View className="report-lead">还没有诊断报告，先去聊两句吧。</View>
          <View className="btn btn-primary" style={{ marginTop: '16px' }} onClick={() => redirect('chat')}>
            去问诊
          </View>
        </View>
      </View>
    );
  }

  const dateLabel = formatReportDate(report.createdAt);

  const handleLeadSuccess = (next: Lead) => {
    const updated = { ...session, lead: next };
    setSession(updated);
    setSheetOpen(false);
    redirect('success');
  };

  return (
    <View className="screen report">
      <View className="topbar">
        <View className="icon-btn" onClick={back}>
          <IconBack />
        </View>
        <View className="topbar-title">你的业务诊断报告</View>
        <View className="icon-btn" onClick={() => redirect('chat')}>
          <IconRestart />
        </View>
      </View>

      <View className="report-inner">
        <View className="report-lead">我帮你理了一下，你看对不对。</View>
        <View className="report-meta">
          <Text className="meta-chip">{dateLabel || '刚刚生成'}</Text>
          <Text className="meta-chip meta-chip-soft">{report.sceneLabel}</Text>
        </View>

        <View className="card pain-card">
          <View className="card-label">
            <IconSpark />
            你的核心痛点
          </View>
          <View className="pain-text">{report.painPoint}</View>
          {!!report.painQuote && <View className="pain-quote">你说的是：「{report.painQuote}」</View>}
        </View>

        <View className="card cost-card">
          <View className="card-label">它带来的代价</View>
          <View className="cost-figure">
            <Text className="cost-num">{report.costValue}</Text>
            <Text className="cost-u">{report.costUnit}</Text>
          </View>
          <View className="cost-note">{report.costNote}</View>
        </View>

        <View className="report-section">
          <View className="section-head">
            <View className="sh-title">初诊方向</View>
            <Text className="sh-sub">先按可能性排了序</Text>
          </View>
          <View className="directions">
            {report.directions.map((direction, index) => (
              <View className="card dir-card" key={direction.id}>
                <View className="dir-head">
                  <Text className="dir-index">{index + 1}</Text>
                  <View className="dir-title">{direction.title}</View>
                </View>
                <Text className={TAG_CLASS[direction.confidence]}>{direction.confidence}置信度</Text>
                <View className="dir-blur">{direction.summary}</View>
              </View>
            ))}
          </View>
        </View>

        <View className="locked">
          <View className="locked-body">
            <View className="card dir-detail">
              <View className="dir-detail-h">完整根因分析</View>
              {(report.directions[0]?.causes || []).map((cause) => (
                <View key={cause}>· {cause}</View>
              ))}
              <View className="dir-detail-h">可以先动的地方</View>
              {(report.directions[0]?.actions || []).map((action) => (
                <View key={action}>· {action}</View>
              ))}
            </View>
          </View>

          <View className="locked-mask">
            <View className="locked-icon">
              <IconLock />
            </View>
            <View className="locked-title">方向细节、完整根因分析</View>
            <View className="locked-text">后面这部分需要一对一再确认，避免给你错的判断。</View>
            <View className="btn btn-primary" onClick={() => setSheetOpen(true)}>
              解锁查看完整诊断与方案
              <IconArrow />
            </View>
            <View className="locked-hint">留个联系方式就能看，不用付费。</View>
          </View>
        </View>

        <View className="card cta-card">
          <View className="cta-title">想真正解决它？让专业的人帮你</View>
          <View className="cta-desc">把这份诊断交给顾问，30 分钟内先聊清楚卡在哪，不推销、不催单。</View>
          {lead ? (
            <View className="lead-done">
              <View className="lead-done-icon">
                <IconCheck />
              </View>
              <View>
                <View className="lead-done-title">已经收到你的联系方式</View>
                <View className="lead-done-text">{maskPhone(lead.phone)} · 顾问会尽快联系你，报告已存好。</View>
              </View>
            </View>
          ) : (
            <View className="btn btn-primary" onClick={() => setSheetOpen(true)}>
              让顾问帮我看看
            </View>
          )}
          <View className="cta-trust">
            <IconShield />
            联系方式仅用于本次问题对接
          </View>
        </View>

        <View className="disclaimer">方向仅供参考，具体方案由专家确认。</View>
      </View>

      <LeadSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onSuccess={handleLeadSuccess}
        conversationId={session.conversationId}
      />
    </View>
  );
}
