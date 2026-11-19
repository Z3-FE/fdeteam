import Taro, { useUnload } from '@tarojs/taro';
import { useRef, useState } from 'react';
import { Input, Text, View } from '@tarojs/components';
import { loadSession, saveAccountPhone, saveSession } from '../../data/consultation';
import { ApiError, saveReportWithPhone, sendSmsCode } from '../../api/client';
import { back } from '../../utils/nav';

const PHONE_RE = /^1\d{10}$/;
const CODE_RE = /^\d{6}$/;

const toast = (title: string) => Taro.showToast({ title, icon: 'none' });

// 保存报告：手机号 + 短信验证码注册账号，报告和选中的方向记为一条留资
export default function Save() {
  const [session] = useState(loadSession);
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [focus, setFocus] = useState<'phone' | 'code' | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useUnload(() => {
    if (timer.current) clearInterval(timer.current);
  });

  const report = session.report;
  if (!report) return null;

  const phoneOk = PHONE_RE.test(phone);
  const canSend = phoneOk && countdown === 0 && !sending;
  const canSubmit = phoneOk && CODE_RE.test(code) && agreed && !saving;

  const startCountdown = (seconds: number) => {
    if (timer.current) clearInterval(timer.current);
    setCountdown(seconds);
    timer.current = setInterval(() => {
      setCountdown((s) => {
        if (s <= 1 && timer.current) {
          clearInterval(timer.current);
          timer.current = null;
        }
        return Math.max(0, s - 1);
      });
    }, 1000);
  };

  const sendCode = async () => {
    if (!phoneOk) {
      toast('请输入 11 位手机号');
      return;
    }
    if (!canSend) return;
    setSending(true);
    try {
      startCountdown(await sendSmsCode(phone));
      toast('验证码已发送');
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 429) {
        toast((err as ApiError).detail === 'daily_limit' ? '今天发送次数太多了，明天再试' : '发送太频繁，请稍后再试');
        if ((err as ApiError).detail === 'cooldown') startCountdown(60);
      } else if (status === 401) toast('登录失败，请重新打开小程序再试');
      else toast('验证码发送失败，请稍后再试');
    } finally {
      setSending(false);
    }
  };

  const submit = async () => {
    if (!canSubmit || !session.conversationId) {
      if (phoneOk && CODE_RE.test(code) && !agreed) toast('请先阅读并勾选服务条款与隐私说明');
      return;
    }
    setSaving(true);
    try {
      const masked = await saveReportWithPhone(session.conversationId, phone, code, session.selectedDirections || []);
      saveSession({ ...loadSession(), savedPhone: masked || phone });
      saveAccountPhone(phone);
      Taro.showToast({ title: '报告已保存', icon: 'success' });
      setTimeout(back, 900);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      toast(status === 400 ? '验证码不对或已过期，请重新获取' : '保存失败，请稍后再试');
      setSaving(false);
    }
  };

  return (
    <View className="screen report-page">
      <View className="fde-scroll">
        <View className="fde-form">
          <View className="fde-kicker">保存报告 · 手机号快速注册</View>
          <View className="fde-title">注册账号并保存报告</View>
          <View className="fde-subtitle">
            填写手机号验证后将自动为你创建账号，报告结论与已选定制方向会同步存档，方便随时回看。
          </View>

          <View className="fde-context-card">
            <View className="fde-context-label">即将保存的诊断摘要</View>
            <View className="fde-context-line">
              {report.sceneLabel} · {report.painPoint}
            </View>
            <View className="fde-context-line">
              预估代价：{report.costValue} {report.costUnit}
              {report.costNote ? `（${report.costNote}）` : ''}
            </View>
          </View>

          <View className="fde-form-group">
            <View className="fde-form-label">手机号</View>
            <View className={`fde-input-box ${focus === 'phone' ? 'is-focused' : ''}`}>
              <Text className="save-phone-prefix">+86</Text>
              <View className="save-phone-sep" />
              <Input
                className="fde-input-field"
                type="number"
                value={phone}
                maxlength={11}
                placeholder="请输入 11 位手机号"
                placeholderClass="fde-input-placeholder"
                onFocus={() => setFocus('phone')}
                onBlur={() => setFocus(null)}
                onInput={(e) => setPhone(e.detail.value.replace(/\D/g, ''))}
              />
            </View>
          </View>

          <View className="fde-form-group">
            <View className="fde-form-label">短信验证码</View>
            <View className={`fde-input-box ${focus === 'code' ? 'is-focused' : ''}`}>
              <Input
                className="fde-input-field"
                type="number"
                value={code}
                maxlength={6}
                placeholder="输入 6 位验证码"
                placeholderClass="fde-input-placeholder"
                onFocus={() => setFocus('code')}
                onBlur={() => setFocus(null)}
                onInput={(e) => setCode(e.detail.value.replace(/\D/g, ''))}
                onConfirm={submit}
              />
              <View
                className={`save-code-btn ${canSend ? 'is-active' : ''}`}
                hoverClass={canSend ? 'is-tap' : 'none'}
                hoverStayTime={60}
                onClick={sendCode}
              >
                {countdown > 0 ? `${countdown}s 后重发` : sending ? '发送中…' : '获取验证码'}
              </View>
            </View>
          </View>

          {/* 协议默认不勾选，勾选后才能提交 */}
          <View className="save-agree" onClick={() => setAgreed((v) => !v)}>
            <View className={`save-agree-box ${agreed ? 'is-checked' : ''}`}>{agreed ? '✓' : ''}</View>
            <Text className="save-agree-text">
              未注册手机号验证后将自动注册个人账号，并同意
              <Text className="save-agree-link">服务条款</Text>与<Text className="save-agree-link">隐私说明</Text>
            </Text>
          </View>
        </View>
      </View>

      <View className="fde-footer">
        <View
          className={`fde-submit ${canSubmit ? 'is-active' : ''}`}
          hoverClass={canSubmit ? 'is-tap' : 'none'}
          hoverStayTime={60}
          onClick={submit}
        >
          {saving ? '保存中…' : '注册账号并保存报告'}
        </View>
        <View className="fde-back" hoverClass="is-tap" hoverStayTime={60} onClick={back}>
          暂不保存，返回报告
        </View>
      </View>
    </View>
  );
}
