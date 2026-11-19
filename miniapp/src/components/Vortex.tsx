import Taro from '@tarojs/taro';
import { useEffect, useRef } from 'react';
import { Canvas, View } from '@tarojs/components';

// 生成页的单色漩涡 loader（AI Studio 原型 logarithmic 预设移植）。
// 刻度、旋臂、虚线内圈、进度弧、括号都画在 Canvas 2D 上，中心百分比用 View 叠在上面。

const CANVAS_ID = 'vortex-canvas';
const INK = '12, 12, 14';
const ARMS = 24;
const DENSITY = 28;
const SPEED = 1;
const STROKE = 1;
const TWIST = 2.2;
const COMPLETE_SECONDS = 0.85;

type Ctx = CanvasRenderingContext2D;

type RafHost = {
  requestAnimationFrame: (cb: (ts: number) => void) => number;
  cancelAnimationFrame: (id: number) => void;
};

interface State {
  last: number;
  phase: number;
  shown: number;
  compT: number;
}

const ink = (alpha: number) => `rgba(${INK}, ${alpha})`;

function drawFrame(ctx: Ctx, size: number, st: State, target: number, ts: number) {
  const dt = st.last ? Math.min(0.05, (ts - st.last) / 1000) : 0.016;
  st.last = ts;

  // 显示值平滑追向真实进度，避免每 100ms 跳一格
  st.shown += (target - st.shown) * Math.min(1, dt * 5);
  if (Math.abs(target - st.shown) < 0.05) st.shown = target;
  const norm = Math.max(0, Math.min(1, st.shown / 100));
  const complete = target >= 100 && st.shown >= 99.5;
  st.compT = complete ? Math.min(1, st.compT + dt / COMPLETE_SECONDS) : 0;
  const compEase = 1 - Math.pow(1 - st.compT, 3);
  st.phase += dt * SPEED * (complete ? 0.35 : 1) * (1 + compEase * 0.75);
  const phase = st.phase;

  const c = size / 2;
  const outer = size * 0.455;
  const eye = size * 0.145;
  const TAU = Math.PI * 2;

  ctx.clearRect(0, 0, size, size);
  ctx.save();
  ctx.translate(c, c);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // 外圈刻度
  for (let i = 0; i < 72; i++) {
    const ang = (i / 72) * TAU;
    const major = i % 6 === 0;
    const r0 = outer + 4;
    const r1 = r0 + (major ? 8 : 3.5);
    ctx.beginPath();
    ctx.moveTo(Math.cos(ang) * r0, Math.sin(ang) * r0);
    ctx.lineTo(Math.cos(ang) * r1, Math.sin(ang) * r1);
    ctx.strokeStyle = ink(major ? 0.32 : 0.12);
    ctx.lineWidth = major ? 1 : 0.75;
    ctx.stroke();
  }

  // 漩涡本体：完成时收缩并淡出
  const vScale = 1 - compEase * 0.72;
  const vAlpha = Math.max(0, 1 - Math.pow(st.compT, 0.85));
  if (vAlpha > 0) {
    ctx.save();
    ctx.scale(vScale, vScale);
    ctx.globalAlpha = vAlpha;

    const steps = Math.max(16, Math.round(DENSITY * 1.4));
    const twist = TWIST * (0.85 + norm * 0.35);
    for (let a = 0; a < ARMS; a++) {
      const base = (a / ARMS) * TAU - phase * 0.9;
      const accent = a % 3 === 0;
      const wave = 0.5 + 0.5 * Math.sin((a / ARMS) * Math.PI * 4 - 2.2 * phase);
      ctx.beginPath();
      for (let s = 0; s <= steps; s++) {
        const t = s / steps;
        const r = eye + (outer - eye) * Math.pow(t, 1.18);
        const th = base + twist * Math.log(1 + 4.5 * t) + Math.sin(TAU * t - 1.5 * phase) * 0.04;
        const x = Math.cos(th) * r;
        const y = Math.sin(th) * r;
        if (s === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = ink(accent ? 0.45 + wave * 0.4 : 0.14 + wave * 0.22);
      ctx.lineWidth = accent ? STROKE * 1.15 : STROKE * 0.75;
      ctx.stroke();
    }

    // 内部虚线弧
    const n = Math.min(18, Math.max(6, Math.round(ARMS / 2)));
    ctx.setLineDash([3, 7]);
    ctx.lineWidth = STROKE * 0.7;
    for (let j = 0; j < n; j++) {
      const r = eye + 8 + (j / n) * (outer - eye) * 0.55;
      const start = phase * (0.4 + (j % 3) * 0.15) + j * 0.6;
      const span = Math.PI * (0.35 + 0.45 * norm);
      ctx.beginPath();
      ctx.arc(0, 0, r, start, start + span);
      ctx.strokeStyle = ink(0.08 + (1 - j / n) * 0.16);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  // 完成冲击波
  if (st.compT > 0 && st.compT < 1) {
    ctx.beginPath();
    ctx.arc(0, 0, eye + compEase * (outer - eye) * 0.42, 0, TAU);
    ctx.strokeStyle = ink((1 - st.compT) * 0.65);
    ctx.lineWidth = 1.25 * (1 - st.compT * 0.5);
    ctx.stroke();
  }

  // 中心：白色眼区 + 轨道 + 进度弧
  ctx.beginPath();
  ctx.arc(0, 0, eye - 2, 0, TAU);
  ctx.fillStyle = '#ffffff';
  ctx.fill();

  ctx.beginPath();
  ctx.arc(0, 0, eye - 3, 0, TAU);
  ctx.strokeStyle = ink(0.16);
  ctx.lineWidth = 1;
  ctx.stroke();

  if (norm > 0) {
    const end = -Math.PI / 2 + norm * TAU;
    ctx.beginPath();
    ctx.arc(0, 0, eye - 3, -Math.PI / 2, end);
    ctx.strokeStyle = ink(0.95);
    ctx.lineWidth = 2;
    ctx.stroke();
    if (norm < 1) {
      ctx.beginPath();
      ctx.arc(Math.cos(end) * (eye - 3), Math.sin(end) * (eye - 3), 2.5, 0, TAU);
      ctx.fillStyle = ink(0.95);
      ctx.fill();
    }
  }

  // 随进度转动的内圈 + 十字刻度
  const innerR = (eye - 10) * (0.92 + norm * 0.08);
  ctx.save();
  ctx.rotate(norm * TAU);
  ctx.beginPath();
  ctx.arc(0, 0, innerR, 0, TAU);
  ctx.strokeStyle = ink(0.08 + norm * 0.14);
  ctx.lineWidth = 0.75;
  ctx.stroke();
  ctx.strokeStyle = ink(0.25 + norm * 0.45);
  for (let k = 0; k < 4; k++) {
    const ang = (k * Math.PI) / 2;
    ctx.beginPath();
    ctx.moveTo(Math.cos(ang) * (innerR - 3), Math.sin(ang) * (innerR - 3));
    ctx.lineTo(Math.cos(ang) * (innerR + 3), Math.sin(ang) * (innerR + 3));
    ctx.stroke();
  }
  ctx.restore();

  // 四段括号弧（原型里是 SVG，这里直接画）
  const bracketR = size * 0.08;
  const half = 0.286;
  ctx.save();
  ctx.rotate(norm * Math.PI);
  ctx.scale(0.88 + norm * 0.14, 0.88 + norm * 0.14);
  ctx.strokeStyle = ink(0.35 + norm * 0.55);
  ctx.lineWidth = 1;
  for (let k = 0; k < 4; k++) {
    const mid = Math.PI / 4 + (k * Math.PI) / 2;
    ctx.beginPath();
    ctx.arc(0, 0, bracketR, mid - half, mid + half);
    ctx.stroke();
  }
  ctx.restore();

  // 中心百分比 + 状态字。直接画进 Canvas：小程序里 View 叠在 Canvas 上会被盖住
  const pct = Math.round(st.shown);
  const textScale = complete ? 1.05 : 0.9 + norm * 0.11 + Math.sin(norm * Math.PI * 8) * 0.014;
  const digits = String(pct).padStart(2, '0');
  const numSize = size * 0.085;
  const unitSize = size * 0.036;
  ctx.save();
  ctx.scale(textScale, textScale);
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  ctx.font = `300 ${numSize}px Menlo, "SF Mono", monospace`;
  const numW = ctx.measureText(digits).width;
  ctx.font = `400 ${unitSize}px Menlo, "SF Mono", monospace`;
  const unitW = ctx.measureText('%').width;
  const left = -(numW + 1 + unitW) / 2;
  const baseline = numSize * 0.28;
  ctx.font = `300 ${numSize}px Menlo, "SF Mono", monospace`;
  ctx.fillStyle = ink(1);
  ctx.fillText(digits, left, baseline);
  ctx.font = `400 ${unitSize}px Menlo, "SF Mono", monospace`;
  ctx.fillStyle = ink(0.55);
  ctx.fillText('%', left + numW + 1, baseline);

  const label = complete ? '已完成' : '生成中';
  const labelSize = size * 0.034;
  ctx.font = `400 ${labelSize}px sans-serif`;
  ctx.fillStyle = ink(0.45);
  // 手动加字距（0.12em），canvas 的 letterSpacing 小程序不支持
  const gap = labelSize * 0.12;
  const chars = label.split('');
  const widths = chars.map((ch) => ctx.measureText(ch).width);
  const total = widths.reduce((sum, w) => sum + w, 0) + gap * (chars.length - 1);
  let x = -total / 2;
  const labelY = baseline + labelSize * 1.9;
  chars.forEach((ch, i) => {
    ctx.fillText(ch, x, labelY);
    x += widths[i] + gap;
  });
  ctx.restore();

  ctx.restore();
}

interface VortexProps {
  progress: number;
}

export function Vortex({ progress }: VortexProps) {
  const progressRef = useRef(progress);
  progressRef.current = progress;

  useEffect(() => {
    let disposed = false;
    let rafId = 0;
    let host: RafHost | null = null;

    const run = (canvas: any, cssW: number) => {
      const dpr = Taro.getSystemInfoSync().pixelRatio || 2;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssW * dpr);
      const ctx = canvas.getContext('2d') as Ctx;
      ctx.scale(dpr, dpr);
      const st: State = { last: 0, phase: 0, shown: 0, compT: 0 };
      host = (process.env.TARO_ENV === 'h5' ? window : canvas) as RafHost;
      const loop = (ts: number) => {
        if (disposed) return;
        drawFrame(ctx, cssW, st, progressRef.current, ts);
        rafId = host!.requestAnimationFrame(loop);
      };
      rafId = host.requestAnimationFrame(loop);
    };

    const init = (attempt: number) => {
      if (disposed) return;
      if (process.env.TARO_ENV === 'h5') {
        const el = document.querySelector(`#${CANVAS_ID}`);
        const canvas = el && (el.tagName === 'CANVAS' ? el : el.querySelector('canvas'));
        if (canvas) run(canvas, (canvas as HTMLCanvasElement).getBoundingClientRect().width || 320);
        else if (attempt < 10) setTimeout(() => init(attempt + 1), 50);
        return;
      }
      Taro.createSelectorQuery()
        .select(`#${CANVAS_ID}`)
        .fields({ node: true, size: true })
        .exec((res) => {
          const r = res && res[0];
          if (r && r.node) run(r.node, r.width || 320);
          else if (attempt < 10) setTimeout(() => init(attempt + 1), 50);
        });
    };

    Taro.nextTick(() => init(0));
    return () => {
      disposed = true;
      if (host && rafId) host.cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <View className="vortex">
      <Canvas type="2d" id={CANVAS_ID} className="vortex-canvas" />
    </View>
  );
}
