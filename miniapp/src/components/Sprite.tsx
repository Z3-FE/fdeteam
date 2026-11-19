import Taro from '@tarojs/taro';
import { useEffect, useRef } from 'react';
import { Canvas } from '@tarojs/components';

// 小精灵：参考 libraries.dev/orbs 的点阵球，Canvas 2D 逐帧绘制。
// 平时：一颗缓慢自转、轻轻呼吸的点阵球；点一下泛起涟漪，点阵向外弹一下、转快一阵。
// 思考中（busy）：球体转快、变淡，一道扫描带上下扫过，几条倾斜轨道上的亮点像彗星一样绕着球转。
// tone="mono" 用在白底黑白主题页面：黑灰点 + 很淡的灰光；pulse 每加 1，点阵向中心收紧再弹开一次。

const CANVAS_ID = 'hero-sprite';
const BUSY_ID = 'busy-sprite';
// 设计坐标系（和 CSS 里 .hero-sprite 的宽高比一致），绘制时按实际尺寸等比缩放
const W = 220;
const H = 180;
const CX = 110;
const CY = 86;
const R = 46;
// 整颗球朝观察者前倾一点，看得到上半球
const VIEW_TILT = 0.38;
const SPHERE_DOTS = 220;
// 黑白主题点更密更细，避免像高尔夫球
const MONO_DOTS = 340;
const MONO_INK = 'rgb(24, 24, 24)';

// 思考中的轨道：tilt 轨道面倾角，yaw 初始方位，count 点数，speed 圈/秒（负数反转），radius 相对球半径
const ORBITS = [
  { tilt: 1.15, yaw: 0.2, count: 28, speed: 0.34, radius: 1.2 },
  { tilt: -0.85, yaw: 1.5, count: 24, speed: -0.27, radius: 1.32 },
  { tilt: 0.3, yaw: -0.9, count: 20, speed: 0.42, radius: 1.1 },
];

// 颜色从品牌蓝渐到青色，预先算好一组，逐点只取下标
const BLUE = [47, 107, 255];
const CYAN = [34, 211, 238];
const PALETTE = Array.from({ length: 16 }, (_, i) => {
  const t = i / 15;
  const c = BLUE.map((b, j) => Math.round(b + (CYAN[j] - b) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
});
// 白底黑白主题用的灰阶：下半球浅灰，上半球接近纯黑
const GRAY = Array.from({ length: 16 }, (_, i) => {
  const v = Math.round(170 - (153 * i) / 15);
  return `rgb(${v}, ${v}, ${v})`;
});

type Ctx = CanvasRenderingContext2D;

interface Vec {
  x: number;
  y: number;
  z: number;
}

interface Dot extends Vec {
  size: number;
  alpha: number;
  color: string;
}

interface Scene {
  frame: (ts: number) => void;
  tap: () => void;
  absorb: () => void;
}

interface SpriteProps {
  busy?: boolean;
  // mono：白底黑点，给黑白主题的页面用
  tone?: 'light' | 'mono';
  // 每次加 1 触发一次"接收指令"：点阵先向中心收紧，再弹开
  pulse?: number;
}

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const TAU = Math.PI * 2;

// 斐波那契球面：点在球面上分布均匀，没有经纬网那种两极扎堆
const fibSphere = (n: number): Vec[] =>
  Array.from({ length: n }, (_, i) => {
    const y = 1 - ((i + 0.5) / n) * 2;
    const ring = Math.sqrt(1 - y * y);
    const a = i * Math.PI * (3 - Math.sqrt(5));
    return { x: Math.cos(a) * ring, y, z: Math.sin(a) * ring };
  });
const SPHERE = fibSphere(SPHERE_DOTS);
const MONO_SPHERE = fibSphere(MONO_DOTS);

// 绕 y 轴转 yaw，再绕 x 轴前倾 tilt；y 朝上，z 朝向观察者
function rotate(p: Vec, yaw: number, tilt: number): Vec {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const x = p.x * cy + p.z * sy;
  const z1 = -p.x * sy + p.z * cy;
  const ct = Math.cos(tilt);
  const st = Math.sin(tilt);
  return { x, y: p.y * ct - z1 * st, z: p.y * st + z1 * ct };
}


// 用 arc + scale 画椭圆，比 ctx.ellipse 兼容性好
function ellipse(ctx: Ctx, x: number, y: number, rx: number, ry: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(Math.max(rx, 0.01), Math.max(ry, 0.01));
  ctx.beginPath();
  ctx.arc(0, 0, 1, 0, TAU);
  ctx.restore();
}

function createScene(ctx: Ctx, busy: boolean, mono: boolean): Scene {
  let start = -1;
  let last = 0;
  let now = 0;
  let spin = 0;
  let tapStart = -10;
  let absorbStart = -10;
  const ripples: number[] = [];
  const dots: Dot[] = [];
  const pal = mono ? GRAY : PALETTE;
  // 按高度取色：浅色主题上青下蓝；黑白主题上深下浅
  const colorAt = (y: number) => pal[Math.round(clamp((y + 1) / 2, 0, 1) * 15)];
  // 光晕、涟漪的底色
  const glowRgb = mono ? '17, 17, 17' : '47, 107, 255';

  // 接收指令：0.18 秒收紧到 0.68 倍，然后带阻尼地弹回，中间会冲过头一点
  const absorbScale = () => {
    const t = (now - absorbStart) / 0.75;
    if (t < 0 || t >= 1) return 1;
    if (t < 0.24) return 1 - 0.32 * Math.sin(((t / 0.24) * Math.PI) / 2);
    const u = (t - 0.24) / 0.76;
    return 1 - 0.32 * (1 - u) * Math.cos(u * Math.PI * 2.5);
  };
  const absorbAmt = () => {
    const t = (now - absorbStart) / 0.75;
    return t >= 0 && t < 1 ? 1 - t : 0;
  };

  // 点击反馈强度：0.9 秒内从 1 衰减到 0
  const tapAmt = () => {
    const t = (now - tapStart) / 0.9;
    return t >= 0 && t < 1 ? Math.pow(1 - t, 2) : 0;
  };

  const pushSphere = (r: number, tap: number) => {
    // 思考中有一道扫描带上下扫过球面，扫到的点变亮变大
    const scanY = Math.sin(now * 1.7) * 0.95;
    for (const base of mono ? MONO_SPHERE : SPHERE) {
      // 表面起伏：沿高度方向的一道慢波，点一下会猛地鼓一下
      const wave = 1 + (0.018 + tap * 0.12) * Math.sin(base.y * 6 - now * 2.4);
      const p = rotate(base, spin, VIEW_TILT);
      const depth = (p.z + 1) / 2;
      // 黑白主题统一深灰，前后层次只靠透明度和大小
      let size = mono ? 0.45 + depth * 0.85 : 0.7 + depth * 1.3;
      let alpha = mono ? 0.1 + depth * 0.8 : 0.16 + depth * 0.74;
      if (busy) {
        const near = Math.max(0, 1 - Math.abs(base.y - scanY) / 0.16);
        alpha = alpha * 0.55 + near * 0.45;
        size += near * 0.8;
      }
      dots.push({
        x: CX + p.x * r * wave,
        y: CY - p.y * r * wave,
        z: p.z,
        size,
        alpha,
        color: mono ? MONO_INK : colorAt(p.y),
      });
    }
  };

  // 轨道上一串点，亮点像彗星一样带着拖尾往前跑
  const pushOrbits = (r: number) => {
    for (const o of ORBITS) {
      const head = (now * o.speed * TAU) % TAU;
      const yaw = o.yaw + now * 0.15;
      for (let i = 0; i < o.count; i++) {
        const a = (i / o.count) * TAU;
        const flat: Vec = { x: Math.cos(a), y: 0, z: Math.sin(a) };
        // 先把轨道面倾斜 o.tilt，再转到自己的方位，最后套上整体前倾
        const tilted: Vec = {
          x: flat.x,
          y: -flat.z * Math.sin(o.tilt),
          z: flat.z * Math.cos(o.tilt),
        };
        const p = rotate(rotate(tilted, yaw, 0), 0, VIEW_TILT);
        // 和亮点的角距离，按运动方向算拖尾
        let d = o.speed > 0 ? head - a : a - head;
        d = ((d % TAU) + TAU) % TAU;
        const trail = Math.pow(Math.max(0, 1 - d / 2.2), 1.6);
        const depth = (p.z + 1) / 2;
        dots.push({
          x: CX + p.x * r * o.radius,
          y: CY - p.y * r * o.radius,
          z: p.z * o.radius,
          size: 0.6 + trail * 1.8 + depth * 0.5,
          alpha: (0.1 + trail * 0.9) * (0.45 + depth * 0.55),
          color: trail > 0.6 ? pal[15] : pal[Math.round(4 + trail * 10)],
        });
      }
    }
  };

  const drawGlow = (r: number, tap: number) => {
    const base = busy ? 0.22 + 0.06 * Math.sin(now * 3) : 0.16 + tap * 0.14 + absorbAmt() * 0.3;
    // 白底上灰光容易显脏，整体压低
    const k = mono ? base * 0.35 : base;
    const g = ctx.createRadialGradient(CX, CY, r * 0.2, CX, CY, r * 1.9);
    g.addColorStop(0, mono ? `rgba(17, 17, 17, ${k})` : `rgba(34, 211, 238, ${k})`);
    g.addColorStop(0.5, `rgba(${glowRgb}, ${k * 0.45})`);
    g.addColorStop(1, `rgba(${glowRgb}, 0)`);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(CX, CY, r * 1.9, 0, TAU);
    ctx.fill();
  };

  return {
    frame(ts: number) {
      if (start < 0) {
        start = ts;
        last = ts;
      }
      const dt = clamp((ts - last) / 1000, 0, 0.05);
      last = ts;
      now = (ts - start) / 1000;
      const tap = tapAmt();
      const absorb = absorbAmt();
      // 平时慢慢自转，思考中转快；点一下、接收指令时都会加速一阵
      spin += dt * ((busy ? 0.95 : 0.28) + tap * 3 + absorb * 6);
      for (let i = ripples.length - 1; i >= 0; i--) {
        ripples[i] += dt;
        if (ripples[i] > 1.2) ripples.splice(i, 1);
      }

      const breath = Math.sin(now * (busy ? 3.2 : 1.8));
      const r = R * (1 + breath * 0.02 + tap * 0.06) * absorbScale();
      const float = busy ? 0 : Math.sin(now * 1.3) * 3;

      ctx.clearRect(0, 0, W, H);

      // 地面投影，球飘高时变小变淡；黑白主题贴近球底、收小
      const f = 1 - float / 30;
      ctx.fillStyle = `rgba(${glowRgb}, ${(mono ? 0.06 : 0.1) * f})`;
      if (mono) ellipse(ctx, CX, CY + R + 12, 24 * f, 2.6 * f);
      else ellipse(ctx, CX, 166, 34 * f, 4 * f);
      ctx.fill();

      ctx.save();
      ctx.translate(0, -float);
      // 白底上的灰光像污渍，黑白主题不画
      if (!mono) drawGlow(r, tap);

      for (const t of ripples) {
        const p = t / 1.2;
        ctx.strokeStyle = `rgba(${glowRgb}, ${(mono ? 0.4 : 0.45) * (1 - p)})`;
        ctx.lineWidth = 1.5 * (1 - p) + 0.5;
        ctx.beginPath();
        ctx.arc(CX, CY, r + 4 + p * 44, 0, TAU);
        ctx.stroke();
      }

      dots.length = 0;
      pushSphere(r, tap);
      if (busy) pushOrbits(r);
      // 由远到近画，轨道转到球后面时自然被前面的点盖住
      dots.sort((a, b) => a.z - b.z);
      let color = '';
      for (const d of dots) {
        if (d.color !== color) {
          color = d.color;
          ctx.fillStyle = color;
        }
        ctx.globalAlpha = d.alpha;
        ctx.beginPath();
        ctx.arc(d.x, d.y, d.size, 0, TAU);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.restore();
    },
    tap() {
      tapStart = now;
      ripples.push(0);
    },
    absorb() {
      absorbStart = now;
      // 弹开那一下同时放出一圈涟漪
      setTimeout(() => ripples.push(0), 180);
    },
  };
}

type RafHost = {
  requestAnimationFrame: (cb: (ts: number) => void) => number;
  cancelAnimationFrame: (id: number) => void;
};

export function Sprite({ busy = false, tone = 'light', pulse = 0 }: SpriteProps) {
  const sceneRef = useRef<Scene | null>(null);
  const id = busy ? BUSY_ID : CANVAS_ID;

  useEffect(() => {
    if (pulse > 0) sceneRef.current?.absorb();
  }, [pulse]);

  useEffect(() => {
    let disposed = false;
    let rafId = 0;
    let host: RafHost | null = null;

    const run = (canvas: any, cssW: number, cssH: number) => {
      const dpr = Taro.getSystemInfoSync().pixelRatio || 2;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      const ctx = canvas.getContext('2d') as Ctx;
      const k = (cssW / W) * dpr;
      ctx.scale(k, k);
      const scene = createScene(ctx, busy, tone === 'mono');
      sceneRef.current = scene;
      host = (process.env.TARO_ENV === 'h5' ? window : canvas) as RafHost;
      const loop = (ts: number) => {
        if (disposed) return;
        scene.frame(ts);
        rafId = host!.requestAnimationFrame(loop);
      };
      rafId = host.requestAnimationFrame(loop);
    };

    const init = (attempt: number) => {
      if (disposed) return;
      if (process.env.TARO_ENV === 'h5') {
        const el = document.querySelector(`#${id}`);
        const canvas = el && (el.tagName === 'CANVAS' ? el : el.querySelector('canvas'));
        if (canvas) {
          const rect = (canvas as HTMLCanvasElement).getBoundingClientRect();
          run(canvas, rect.width || W, rect.height || H);
        } else if (attempt < 10) setTimeout(() => init(attempt + 1), 50);
        return;
      }
      Taro.createSelectorQuery()
        .select(`#${id}`)
        .fields({ node: true, size: true })
        .exec((res) => {
          const r = res && res[0];
          if (r && r.node) run(r.node, r.width || W, r.height || H);
          else if (attempt < 10) setTimeout(() => init(attempt + 1), 50);
        });
    };

    Taro.nextTick(() => init(0));
    return () => {
      disposed = true;
      if (host && rafId) host.cancelAnimationFrame(rafId);
      sceneRef.current = null;
    };
  }, []);

  return (
    <Canvas
      type="2d"
      id={id}
      className={busy ? 'busy-sprite' : 'hero-sprite'}
      onTouchStart={busy ? undefined : () => sceneRef.current?.tap()}
    />
  );
}
