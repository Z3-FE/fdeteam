import Taro from '@tarojs/taro';
import { useEffect, useRef } from 'react';
import { Canvas } from '@tarojs/components';

// 落地页小精灵：一颗会呼吸的发光能量球，Canvas 2D 逐帧绘制。
// 平时眨眼、张望，隔一阵自己做个鬼脸（眨眼 / 坏笑 / 吐舌头 / 星星眼 / 认真听）；
// 点一下随机给个反应并泛起涟漪；1.5 秒内连点 4 下会晕乎乎；16 秒不碰就打瞌睡，点它会被吓醒。

const CANVAS_ID = 'hero-sprite';
// 设计坐标系（和 CSS 里 .hero-sprite 的宽高一致），绘制时按实际尺寸等比缩放
const W = 220;
const H = 180;
const CX = 110;
const CY = 88;
const R = 42;

const GOLD = '#ffd36e';
const TONGUE = '#ff6b8a';
const ORBIT_COLORS = [GOLD, '#ffb59a', '#ffffff'];

type Ctx = CanvasRenderingContext2D;

type Expr =
  | 'idle'
  | 'wink'
  | 'smirk'
  | 'tongue'
  | 'starry'
  | 'happy'
  | 'love'
  | 'surprised'
  | 'shy'
  | 'dizzy'
  | 'sleepy'
  | 'listen';

// 每个表情持续多久（秒）；不写的会一直保持，直到被别的事件打断
const DURATION: Partial<Record<Expr, number>> = {
  wink: 1.6,
  smirk: 2.0,
  tongue: 1.8,
  starry: 2.0,
  happy: 1.4,
  love: 1.8,
  surprised: 1.2,
  shy: 1.8,
  dizzy: 2.6,
  listen: 2.2,
};
const IDLE_PICKS: Expr[] = ['wink', 'smirk', 'tongue', 'starry', 'listen'];
const TAP_PICKS: Expr[] = ['happy', 'love', 'surprised', 'shy', 'tongue', 'wink'];
const BLUSH: Partial<Record<Expr, number>> = {
  shy: 0.6,
  happy: 0.4,
  love: 0.45,
  tongue: 0.35,
  starry: 0.3,
  wink: 0.3,
};
const SLEEP_AFTER = 16;

interface Particle {
  kind: 'heart' | 'star' | 'z';
  x: number;
  y: number;
  vx: number;
  vy: number;
  age: number;
  life: number;
  size: number;
}

interface Orbiter {
  a: number;
  r: number;
  speed: number;
  tilt: number;
  size: number;
  hue: number;
}

interface Scene {
  frame: (now: number) => void;
  tap: () => void;
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const pick = <T,>(list: T[]) => list[Math.floor(Math.random() * list.length)];
const easeOutBack = (x: number) => 1 + 2.70158 * Math.pow(x - 1, 3) + 1.70158 * Math.pow(x - 1, 2);

// 用 arc + scale 画椭圆，比 ctx.ellipse 兼容性好
function ellipse(ctx: Ctx, x: number, y: number, rx: number, ry: number, rot = 0) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot);
  ctx.scale(Math.max(rx, 0.01), Math.max(ry, 0.01));
  ctx.beginPath();
  ctx.arc(0, 0, 1, 0, Math.PI * 2);
  ctx.restore();
}

function roundRect(ctx: Ctx, x: number, y: number, w: number, h: number, r: number) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function heart(ctx: Ctx, x: number, y: number, s: number) {
  ctx.beginPath();
  ctx.moveTo(x, y + s * 0.35);
  ctx.bezierCurveTo(x - s, y - s * 0.4, x - s * 0.45, y - s, x, y - s * 0.45);
  ctx.bezierCurveTo(x + s * 0.45, y - s, x + s, y - s * 0.4, x, y + s * 0.35);
  ctx.closePath();
}

function star5(ctx: Ctx, x: number, y: number, r: number, rot = 0) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * Math.PI * 2 - Math.PI / 2 + rot;
    const rr = i % 2 === 0 ? r : r * 0.45;
    const px = x + Math.cos(a) * rr;
    const py = y + Math.sin(a) * rr;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
}

// 蚊香眼
function spiral(ctx: Ctx, x: number, y: number, r: number, rot: number) {
  const n = 40;
  ctx.beginPath();
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const a = t * 2.2 * Math.PI * 2 + rot;
    const px = x + Math.cos(a) * r * t;
    const py = y + Math.sin(a) * r * t;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
}

// 弧线：从 (x-w, y) 到 (x+w, y)，h > 0 向上拱，h < 0 向下弯
function arcLine(ctx: Ctx, x: number, y: number, w: number, h: number) {
  ctx.beginPath();
  ctx.moveTo(x - w, y);
  ctx.quadraticCurveTo(x, y - h, x + w, y);
  ctx.stroke();
}

// k：设计坐标到画布像素的倍率，只用来换算阴影（shadowBlur 不受 transform 影响）
function createScene(ctx: Ctx, k: number): Scene {
  let start = -1;
  let last = 0;
  let now = 0;
  let blinkAt = 1.6;
  let blinkStart = -10;
  let lookX = 0;
  let tgtX = 0;
  let lookAt = 1.5;
  let expr: Expr = 'idle';
  let exprStart = 0;
  let nextPlay = 4;
  let lastTouch = 0;
  let emitAt = 0;
  let tapStart = -10;
  let jumpStart = -10;
  const taps: number[] = [];
  const ripples: number[] = [];
  const parts: Particle[] = [];
  // 环绕粒子：倾斜轨道上转圈，转到球后面时画在球体之下
  const orbiters: Orbiter[] = Array.from({ length: 14 }, (_, i) => ({
    a: (i / 14) * Math.PI * 2 + rand(-0.2, 0.2),
    r: rand(54, 70),
    speed: rand(0.5, 0.9) * (i % 2 ? 1 : -1),
    tilt: rand(0.22, 0.38),
    size: rand(1.4, 2.8),
    hue: i % 3,
  }));

  const setExpr = (name: Expr) => {
    expr = name;
    exprStart = now;
    if (name === 'happy' || name === 'surprised') jumpStart = now;
  };
  const exprT = () => {
    const d = DURATION[expr];
    return d ? (now - exprStart) / d : 0;
  };
  const tapAmt = () => {
    const t = (now - tapStart) / 0.8;
    return t >= 0 && t < 1 ? Math.sin(t * Math.PI) * (1 - t) : 0;
  };
  const spawn = (p: Omit<Particle, 'age'>) => parts.push({ ...p, age: 0 });

  // 返回"认真听"的强度 0~1
  const update = (dt: number) => {
    // 眨眼：偶尔连眨两下
    if (now >= blinkAt) {
      blinkStart = now;
      blinkAt = now + (Math.random() < 0.2 ? 0.28 : rand(2.6, 5));
    }
    if (now >= lookAt) {
      tgtX = Math.random() < 0.4 ? 0 : rand(-1, 1);
      lookAt = now + rand(1.5, 3.2);
    }
    const want =
      expr === 'shy' ? 1 : expr === 'smirk' ? -0.6 : expr === 'idle' || expr === 'listen' ? tgtX : 0;
    lookX += (want - lookX) * (1 - Math.pow(0.002, dt));

    if (DURATION[expr] && exprT() >= 1) {
      setExpr('idle');
      nextPlay = now + rand(5, 8);
    }
    if (expr === 'idle' && now - lastTouch > SLEEP_AFTER) setExpr('sleepy');
    else if (expr === 'idle' && now >= nextPlay) setExpr(pick(IDLE_PICKS));

    // 表情附带的小粒子
    if (now >= emitAt) {
      if (expr === 'love') {
        spawn({ kind: 'heart', x: CX + rand(-30, 30), y: CY - 30, vx: rand(-12, 12), vy: rand(-50, -30), life: 1.3, size: rand(4, 6.5) });
        emitAt = now + 0.22;
      } else if (expr === 'starry') {
        spawn({ kind: 'star', x: CX + rand(-60, 60), y: CY + rand(-50, 30), vx: 0, vy: -6, life: 0.7, size: rand(3, 5) });
        emitAt = now + 0.15;
      } else if (expr === 'sleepy') {
        spawn({ kind: 'z', x: CX + 28, y: CY - 34, vx: rand(10, 16), vy: -20, life: 2.2, size: rand(9, 12) });
        emitAt = now + 1.1;
      }
    }

    const listen = expr === 'listen' ? Math.sin(clamp(exprT(), 0, 1) * Math.PI) : 0;
    const spin = expr === 'dizzy' ? 5 : expr === 'sleepy' ? -0.6 : 0;
    const boost = 1 + listen * 1.5 + tapAmt() * 4 + spin;
    for (const o of orbiters) o.a += o.speed * dt * boost;
    for (let i = ripples.length - 1; i >= 0; i--) {
      ripples[i] += dt;
      if (ripples[i] > 1.2) ripples.splice(i, 1);
    }
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      p.age += dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      if (p.kind === 'z') p.x += Math.sin(p.age * 4) * 0.3;
      if (p.age >= p.life) parts.splice(i, 1);
    }
    return listen;
  };

  // 球的轮廓：几层正弦叠加，amp 越大越"果冻"
  const shape = (r: number, amp: number) => {
    const n = 64;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      const w =
        1 +
        amp *
          (0.5 * Math.sin(a * 3 + now * 2.1) +
            0.3 * Math.sin(a * 5 - now * 3.3) +
            0.2 * Math.sin(a * 2 + now * 1.4));
      const x = CX + Math.cos(a) * r * w;
      const y = CY + Math.sin(a) * r * w;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
  };

  const drawOrbiters = (front: boolean) => {
    for (const o of orbiters) {
      const s = Math.sin(o.a);
      if (s > 0 !== front) continue;
      const x = CX + Math.cos(o.a) * o.r;
      const y = CY + s * o.r * o.tilt - Math.cos(o.a) * 6;
      const color = ORBIT_COLORS[o.hue];
      ctx.save();
      ctx.globalAlpha = (front ? 0.95 : 0.4) * (expr === 'sleepy' ? 0.5 : 1);
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = 6 * k;
      ctx.beginPath();
      ctx.arc(x, y, o.size * (front ? 1 : 0.75), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  };
  const drawOrb = (r: number, amp: number, listen: number, tap: number) => {
    // 外层光晕
    const halo = ctx.createRadialGradient(CX, CY, r * 0.6, CX, CY, r * 2);
    const hk = expr === 'sleepy' ? 0.18 : 0.35 + listen * 0.2 + tap * 0.3;
    halo.addColorStop(0, `rgba(255, 140, 100, ${hk})`);
    halo.addColorStop(1, 'rgba(255, 140, 100, 0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(CX, CY, r * 2, 0, Math.PI * 2);
    ctx.fill();

    // 点击涟漪
    for (const t of ripples) {
      const p = t / 1.2;
      ctx.strokeStyle = `rgba(255, 122, 89, ${0.6 * (1 - p)})`;
      ctx.lineWidth = 2.5 * (1 - p) + 0.5;
      ctx.beginPath();
      ctx.arc(CX, CY, r + p * 48, 0, Math.PI * 2);
      ctx.stroke();
    }

    drawOrbiters(false);

    // 主体：径向渐变，内部有几团颜色慢慢流动
    ctx.save();
    shape(r, amp);
    const g = ctx.createRadialGradient(CX - r * 0.35, CY - r * 0.4, r * 0.1, CX, CY, r * 1.1);
    g.addColorStop(0, '#ffe0cf');
    g.addColorStop(0.45, '#ff9a76');
    g.addColorStop(1, '#f2643f');
    ctx.fillStyle = g;
    ctx.fill();
    ctx.clip();
    const blobs: [number, number, string, number][] = [
      [Math.cos(now * 0.9) * 0.4, Math.sin(now * 1.1) * 0.35, 'rgba(255, 211, 110, 0.55)', 0.6],
      [Math.cos(now * 0.7 + 2) * 0.45, Math.sin(now * 0.8 + 1) * 0.4, 'rgba(255, 92, 120, 0.35)', 0.55],
      [Math.cos(now * 1.2 + 4) * 0.35, Math.sin(now * 0.6 + 3) * 0.45, 'rgba(255, 255, 255, 0.35)', 0.4],
    ];
    for (const [dx, dy, color, s] of blobs) {
      const bx = CX + dx * r;
      const by = CY + dy * r;
      const br = r * s * (1 + listen * 0.3);
      const bg = ctx.createRadialGradient(bx, by, 0, bx, by, br);
      bg.addColorStop(0, color);
      bg.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = bg;
      ctx.fillRect(CX - r * 1.3, CY - r * 1.3, r * 2.6, r * 2.6);
    }
    ctx.restore();

    // 高光
    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
    ellipse(ctx, CX - r * 0.38, CY - r * 0.48, r * 0.22, r * 0.11, -0.6);
    ctx.fill();
  };
  const drawFace = () => {
    const t = now - exprStart;
    // 切换表情时脸"弹"一下
    const pp = t / 0.35;
    const pop = pp >= 0 && pp < 1 ? easeOutBack(pp) : 1;
    const fx = CX + lookX * 7;
    const fy = CY - 2;
    const ey = fy;
    const lx = fx - 12;
    const rx = fx + 12;
    ctx.save();
    ctx.translate(fx, fy);
    ctx.scale(pop, pop);
    ctx.translate(-fx, -fy);

    // 腮红
    ctx.fillStyle = `rgba(255, 80, 110, ${BLUSH[expr] ?? 0.18})`;
    ellipse(ctx, fx - 22, fy + 10, 6, 3.5);
    ctx.fill();
    ellipse(ctx, fx + 22, fy + 10, 6, 3.5);
    ctx.fill();

    ctx.fillStyle = '#fff';
    ctx.strokeStyle = '#fff';
    ctx.shadowColor = 'rgba(255, 255, 255, 0.9)';
    ctx.shadowBlur = 8 * k;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3.4;

    const bt = (now - blinkStart) / 0.16;
    const open = bt >= 0 && bt < 1 ? Math.abs(Math.cos(bt * Math.PI)) : 1;
    const pill = (x: number) => {
      const h = Math.max(2, 12 * open);
      roundRect(ctx, x - 2.6, ey - h / 2, 5.2, h, 2.6);
      ctx.fill();
    };
    const mouth = (fn: () => void) => {
      ctx.save();
      ctx.lineWidth = 2.6;
      fn();
      ctx.restore();
    };

    switch (expr) {
      case 'wink': {
        pill(lx);
        arcLine(ctx, rx, ey + 1, 5, 5);
        mouth(() => arcLine(ctx, fx + 1, fy + 12, 4.5, -4));
        // 眨眼那侧闪一颗小星
        const s = Math.sin(clamp(t / 0.6, 0, 1) * Math.PI);
        ctx.fillStyle = GOLD;
        ctx.shadowColor = GOLD;
        star5(ctx, fx + 26, ey - 10, 4.5 * s, t * 3);
        ctx.fill();
        break;
      }
      case 'smirk': {
        // 半眯眼斜着看，一边眉毛挑起
        for (const x of [lx, rx]) {
          ctx.beginPath();
          ctx.arc(x, ey - 1, 4.2, 0, Math.PI);
          ctx.closePath();
          ctx.fill();
        }
        ctx.save();
        ctx.lineWidth = 2.4;
        ctx.beginPath();
        ctx.moveTo(lx - 5, ey - 4);
        ctx.lineTo(lx + 4, ey - 5);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(rx - 4, ey - 8);
        ctx.lineTo(rx + 5, ey - 6);
        ctx.stroke();
        ctx.restore();
        mouth(() => {
          ctx.beginPath();
          ctx.moveTo(fx - 6, fy + 13);
          ctx.quadraticCurveTo(fx + 2, fy + 15, fx + 7, fy + 9);
          ctx.stroke();
        });
        break;
      }
      case 'tongue': {
        // > < 眯眼 + 晃来晃去的舌头
        ctx.save();
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(lx - 4, ey - 5);
        ctx.lineTo(lx + 3, ey);
        ctx.lineTo(lx - 4, ey + 5);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(rx + 4, ey - 5);
        ctx.lineTo(rx - 3, ey);
        ctx.lineTo(rx + 4, ey + 5);
        ctx.stroke();
        ctx.restore();
        const wig = Math.sin(t * 14) * 1.5;
        ctx.save();
        ctx.shadowBlur = 0;
        ctx.fillStyle = TONGUE;
        roundRect(ctx, fx - 4 + wig, fy + 11, 8, 9 + Math.sin(t * 7) * 1.2, 4);
        ctx.fill();
        ctx.strokeStyle = 'rgba(200, 40, 80, 0.5)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(fx + wig, fy + 13);
        ctx.lineTo(fx + wig, fy + 17);
        ctx.stroke();
        ctx.restore();
        mouth(() => arcLine(ctx, fx, fy + 11, 7, -2));
        break;
      }
      case 'starry': {
        const s = 1 + Math.sin(t * 10) * 0.12;
        ctx.save();
        ctx.fillStyle = '#fff6cc';
        ctx.strokeStyle = GOLD;
        ctx.shadowColor = GOLD;
        ctx.shadowBlur = 10 * k;
        ctx.lineWidth = 1.4;
        star5(ctx, lx, ey, 8 * s, t * 1.5);
        ctx.fill();
        ctx.stroke();
        star5(ctx, rx, ey, 8 * s, -t * 1.5);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
        ctx.beginPath();
        ctx.moveTo(fx - 5, fy + 11);
        ctx.quadraticCurveTo(fx, fy + 20, fx + 5, fy + 11);
        ctx.closePath();
        ctx.fill();
        break;
      }
      case 'happy': {
        arcLine(ctx, lx, ey + 2, 5, 6);
        arcLine(ctx, rx, ey + 2, 5, 6);
        ctx.beginPath();
        ctx.moveTo(fx - 7, fy + 10);
        ctx.quadraticCurveTo(fx, fy + 22, fx + 7, fy + 10);
        ctx.closePath();
        ctx.fill();
        break;
      }
      case 'love': {
        const s = 6.5 * (1 + Math.max(0, Math.sin(t * 9)) * 0.22);
        ctx.save();
        ctx.fillStyle = '#ff5c7a';
        ctx.shadowColor = 'rgba(255, 92, 122, 0.9)';
        heart(ctx, lx, ey + 1, s);
        ctx.fill();
        heart(ctx, rx, ey + 1, s);
        ctx.fill();
        ctx.restore();
        mouth(() => arcLine(ctx, fx, fy + 11, 4.5, -4));
        break;
      }
      case 'surprised': {
        for (const x of [lx, rx]) {
          ctx.beginPath();
          ctx.arc(x, ey - 1, 5.2, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.save();
        ctx.lineWidth = 2.2;
        arcLine(ctx, lx, ey - 11, 4, 2.5);
        arcLine(ctx, rx, ey - 11, 4, 2.5);
        ctx.restore();
        mouth(() => {
          ctx.beginPath();
          ctx.arc(fx, fy + 14, 3.2, 0, Math.PI * 2);
          ctx.stroke();
        });
        break;
      }
      case 'shy': {
        arcLine(ctx, lx, ey + 2, 4.5, 4.5);
        arcLine(ctx, rx, ey + 2, 4.5, 4.5);
        mouth(() => {
          ctx.beginPath();
          ctx.moveTo(fx - 5, fy + 12);
          ctx.quadraticCurveTo(fx - 2.5, fy + 9, fx, fy + 12);
          ctx.quadraticCurveTo(fx + 2.5, fy + 15, fx + 5, fy + 12);
          ctx.stroke();
        });
        // 腮上三道斜线
        ctx.save();
        ctx.lineWidth = 1.6;
        ctx.strokeStyle = 'rgba(255, 80, 110, 0.7)';
        ctx.shadowBlur = 0;
        for (const side of [-1, 1]) {
          for (let i = 0; i < 3; i++) {
            const bx = fx + side * 22 - 4 + i * 3.5;
            ctx.beginPath();
            ctx.moveTo(bx, fy + 8);
            ctx.lineTo(bx + 2, fy + 12);
            ctx.stroke();
          }
        }
        ctx.restore();
        break;
      }
      case 'dizzy': {
        ctx.save();
        ctx.lineWidth = 2.2;
        spiral(ctx, lx, ey, 6.5, t * 9);
        ctx.stroke();
        spiral(ctx, rx, ey, 6.5, t * 9);
        ctx.stroke();
        ctx.restore();
        mouth(() => {
          ctx.beginPath();
          for (let i = 0; i <= 12; i++) {
            const x = fx - 7 + (i / 12) * 14;
            const y = fy + 13 + Math.sin(i * 1.4 + t * 8) * 1.8;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          ctx.stroke();
        });
        break;
      }
      case 'sleepy': {
        ctx.save();
        ctx.lineWidth = 2.8;
        arcLine(ctx, lx, ey + 1, 5, -3.5);
        arcLine(ctx, rx, ey + 1, 5, -3.5);
        ctx.restore();
        // 嘴里吹的小泡泡
        const b = 2 + (0.5 + 0.5 * Math.sin(now * 1.6)) * 1.6;
        mouth(() => {
          ctx.beginPath();
          ctx.arc(fx + 2, fy + 13, b, 0, Math.PI * 2);
          ctx.stroke();
        });
        break;
      }
      case 'listen': {
        arcLine(ctx, lx, ey + 2, 5, 6);
        arcLine(ctx, rx, ey + 2, 5, 6);
        break;
      }
      default:
        pill(lx);
        pill(rx);
    }
    ctx.restore();
  };
  const drawParticles = () => {
    for (const p of parts) {
      const t = p.age / p.life;
      ctx.save();
      ctx.globalAlpha = t < 0.15 ? t / 0.15 : 1 - Math.pow((t - 0.15) / 0.85, 2);
      if (p.kind === 'heart') {
        ctx.fillStyle = '#ff5c7a';
        heart(ctx, p.x, p.y, p.size);
        ctx.fill();
      } else if (p.kind === 'star') {
        ctx.fillStyle = GOLD;
        star5(ctx, p.x, p.y, p.size * Math.sin(t * Math.PI), t * 4);
        ctx.fill();
      } else {
        ctx.fillStyle = '#e85c3f';
        ctx.font = `bold ${p.size * (0.7 + t * 0.5)}px sans-serif`;
        ctx.fillText('z', p.x, p.y);
      }
      ctx.restore();
    }
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
      const listen = update(dt);
      const tap = tapAmt();
      const t = now - exprStart;
      const sleepy = expr === 'sleepy';

      // 呼吸 + 漂浮；睡着时呼吸更慢更深，身子往下沉一点
      const breath = Math.sin(now * (sleepy ? 1.1 : 2.2));
      const r = R * (1 + breath * (sleepy ? 0.04 : 0.025) + tap * 0.12);
      const amp = 0.018 + listen * 0.05 + tap * 0.08 + (expr === 'dizzy' ? 0.04 : 0);
      const jp = (now - jumpStart) / 0.55;
      const jump = jp >= 0 && jp < 1 ? Math.sin(jp * Math.PI) * (expr === 'surprised' ? 14 : 20) : 0;
      const float =
        (sleepy ? -3 : 0) + Math.sin(now * (sleepy ? 0.8 : 1.6)) * (sleepy ? 1.5 : 4) + jump;

      // 不同表情配不同的身体动作
      let rot = 0;
      let sx = 1;
      let sy = 1;
      let ox = 0;
      if (expr === 'dizzy') {
        rot = Math.sin(t * 7) * 0.14;
        ox = Math.sin(t * 3.5) * 5;
      } else if (expr === 'shy') {
        rot = 0.12 * Math.min(1, t * 4);
        sx = 1.03;
        sy = 0.97;
      } else if (expr === 'smirk') {
        rot = -0.06;
      } else if (sleepy) {
        rot = 0.08 + Math.sin(now * 0.8) * 0.03;
        sx = 1.04;
        sy = 0.95;
      } else if (expr === 'tongue') {
        rot = Math.sin(t * 6) * 0.05;
      } else if (expr === 'wink') {
        rot = Math.sin(clamp(t / 0.5, 0, 1) * Math.PI) * 0.09;
      }
      // 起跳和落地时压扁，空中拉长
      if (jp >= 0 && jp < 1) {
        const squash = jp < 0.15 ? jp / 0.15 : jp > 0.85 ? (1 - jp) / 0.15 : 0;
        sx += 0.1 * squash;
        sy -= 0.1 * squash;
        if (jp > 0.2 && jp < 0.8) {
          sx -= 0.04;
          sy += 0.05;
        }
      }

      ctx.clearRect(0, 0, W, H);
      const f = clamp(1 - (float + 4) / 40, 0.45, 1);
      ctx.fillStyle = `rgba(232, 92, 63, ${0.14 * f})`;
      ellipse(ctx, CX + ox * 0.5, 166, 30 * f, 4.5 * f);
      ctx.fill();

      ctx.save();
      ctx.translate(CX + ox, CY + R - float);
      ctx.rotate(rot);
      ctx.scale(sx, sy);
      ctx.translate(-CX, -(CY + R));
      drawOrb(r, amp, listen, tap);
      drawFace();
      drawOrbiters(true);
      ctx.restore();

      drawParticles();
    },
    tap() {
      lastTouch = now;
      tapStart = now;
      ripples.push(0);
      taps.push(now);
      while (taps.length && now - taps[0] > 1.5) taps.shift();
      if (expr === 'sleepy') {
        setExpr('surprised');
        taps.length = 0;
        return;
      }
      if (taps.length >= 4) {
        setExpr('dizzy');
        taps.length = 0;
        return;
      }
      if (expr === 'dizzy') return;
      let next = pick(TAP_PICKS);
      while (next === expr) next = pick(TAP_PICKS);
      setExpr(next);
    },
  };
}

type RafHost = {
  requestAnimationFrame: (cb: (ts: number) => void) => number;
  cancelAnimationFrame: (id: number) => void;
};

export function Sprite() {
  const sceneRef = useRef<Scene | null>(null);

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
      const scene = createScene(ctx, k);
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
        const el = document.querySelector(`#${CANVAS_ID}`);
        const canvas = el && (el.tagName === 'CANVAS' ? el : el.querySelector('canvas'));
        if (canvas) {
          const rect = (canvas as HTMLCanvasElement).getBoundingClientRect();
          run(canvas, rect.width || W, rect.height || H);
        } else if (attempt < 10) setTimeout(() => init(attempt + 1), 50);
        return;
      }
      Taro.createSelectorQuery()
        .select(`#${CANVAS_ID}`)
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
      id={CANVAS_ID}
      className="hero-sprite"
      onTouchStart={() => sceneRef.current?.tap()}
    />
  );
}