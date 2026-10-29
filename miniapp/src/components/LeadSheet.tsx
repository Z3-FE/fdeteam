import { useEffect, useState } from 'react';
import { Button, Input, Text, View } from '@tarojs/components';
import { IconWeChat } from './icons';
import type { Lead } from '../data/consultation';
import { postLead } from '../api/client';

interface LeadSheetProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (lead: Lead) => void;
  conversationId: string | null;
}

type Tab = 'wechat' | 'sms';

export function LeadSheet({ open, onClose, onSuccess, conversationId }: LeadSheetProps) {
  const [tab, setTab] = useState<Tab>('wechat');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (countdown <= 0) return;
    const id = setTimeout(() => setCountdown((v) => v - 1), 1000);
    return () => clearTimeout(id);
  }, [countdown]);

  if (!open) return null;

  const phoneValid = /^1\d{10}$/.test(phone);
  const codeValid = /^\d{4,6}$/.test(code);

  const finish = (channel: Lead['channel'], value: string) => {
    if (conversationId) {
      postLead(conversationId, channel, value).catch(() => {});
    }
    onSuccess({ channel, phone: value, createdAt: Date.now() });
  };

  const handleWeChat = () => {
    if (sending || submitting) return;
    setSending(true);
    setTimeout(() => {
      setSending(false);
      finish('wechat', '13800001234');
    }, 800);
  };

  const handleSendCode = () => {
    if (!phoneValid || countdown > 0) return;
    setCodeSent(true);
    setCountdown(60);
  };

  const handleSmsSubmit = () => {
    if (!phoneValid || !codeValid || submitting) return;
    setSubmitting(true);
    setTimeout(() => {
      setSubmitting(false);
      finish('sms', phone);
    }, 600);
  };

  return (
    <View className="sheet-root">
      <View className="sheet-backdrop" onClick={onClose} />
      <View className="sheet-panel">
        <View className="sheet-handle" />
        <View className="sheet-title">留个联系方式，我们安排人跟你聊聊</View>
        <View className="sheet-note">不会打扰你，暂时不想推进放着就行。</View>

        <View className="sheet-tabs">
          <View className={`sheet-tab ${tab === 'wechat' ? 'is-active' : ''}`} onClick={() => setTab('wechat')}>
            微信授权
          </View>
          <View className={`sheet-tab ${tab === 'sms' ? 'is-active' : ''}`} onClick={() => setTab('sms')}>
            手机号验证
          </View>
        </View>

        {tab === 'wechat' ? (
          <View className="sheet-body">
            <Button className="btn btn-wechat" onClick={handleWeChat} disabled={sending}>
              <IconWeChat />
              {sending ? '正在唤起微信授权…' : '微信一键授权手机号'}
            </Button>
            <View className="sheet-tip">授权后只获取手机号，不会发朋友圈、不读取其他信息。</View>
          </View>
        ) : (
          <View className="sheet-body">
            <View className="field">
              <Text className="field-label">手机号</Text>
              <Input
                className="field-input"
                type="number"
                maxlength={11}
                value={phone}
                placeholder="填一个方便接电话的号码"
                onInput={(e) => setPhone(e.detail.value.replace(/\D/g, ''))}
              />
            </View>
            <View className="field">
              <Text className="field-label">验证码</Text>
              <View className="code-row">
                <Input
                  className="field-input"
                  type="number"
                  maxlength={6}
                  value={code}
                  placeholder="4~6 位数字"
                  onInput={(e) => setCode(e.detail.value.replace(/\D/g, ''))}
                />
                <View
                  className={`code-btn ${!phoneValid || countdown > 0 ? 'is-disabled' : ''}`}
                  onClick={handleSendCode}
                >
                  {countdown > 0 ? `${countdown}s 后重发` : codeSent ? '重新获取' : '获取验证码'}
                </View>
              </View>
            </View>
            <View
              className={`btn btn-primary ${!phoneValid || !codeValid || submitting ? 'is-disabled' : ''}`}
              onClick={handleSmsSubmit}
            >
              {submitting ? '正在提交…' : '提交，等专家联系我'}
            </View>
          </View>
        )}

        <View className="sheet-privacy">仅用于本次问题对接。</View>
        <View className="sheet-skip" onClick={onClose}>
          先不用，谢谢
        </View>
      </View>
    </View>
  );
}
