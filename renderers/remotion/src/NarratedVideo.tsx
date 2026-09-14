import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, interpolate, Easing, staticFile, useCurrentFrame} from 'remotion';

type Plan = {
  width: number; height: number; fps: number; total_frames: number;
  shots: any[]; motion?: {max_zoom?: number; easing?: string};
};

const ease = Easing.inOut(Easing.ease);

const mediaStyle = (shot: any, frame: number, plan: Plan): React.CSSProperties => {
  const local = frame - shot.start_frame;
  const maxZoom = plan.motion?.max_zoom ?? 0.06;
  const progress = shot.duration_frames <= 1 ? 0 : local / (shot.duration_frames - 1);
  const p = Math.max(0, Math.min(1, progress));
  const eased = shot.motion === 'still' ? 0 : interpolate(p, [0, 1], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  let x = 0; let y = 0; let scale = 1;
  if (shot.motion === 'push') scale = 1 + maxZoom * eased;
  if (shot.motion === 'pull') scale = 1 + maxZoom * (1 - eased);
  if (shot.motion === 'pan-left') x = maxZoom * (0.5 - eased);
  if (shot.motion === 'pan-right') x = maxZoom * (eased - 0.5);
  const fade = shot.transition_frames && local < shot.transition_frames
    ? interpolate(local, [0, shot.transition_frames], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  return {width: '100%', height: '100%', objectFit: 'cover', transform: `translate(${x * 100}%, ${y * 100}%) scale(${scale})`, opacity: fade};
};

const Layer: React.FC<{layer: any; frame: number}> = ({layer, frame}) => {
  const local = frame - layer._shot_start - Math.round(layer.start * layer._fps);
  const frames = Math.max(1, Math.round((layer.end - layer.start) * layer._fps));
  const k = layer.keyframes ?? [];
  const a = k.length ? k[0] : {x: 0.5, y: 0.5, scale: 1, rotation: 0, opacity: 1};
  const b = k.length ? k[k.length - 1] : a;
  const t = Math.max(0, Math.min(1, local / frames));
  const value = (key: string) => interpolate(t, [0, 1], [a[key], b[key]], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const style: React.CSSProperties = {position: 'absolute', left: `${value('x') * 100}%`, top: `${value('y') * 100}%`, width: `${(layer.width ?? 0.3) * 100}%`, height: `${(layer.height ?? 0.3) * 100}%`, objectFit: 'contain', transform: `translate(-50%, -50%) scale(${value('scale')}) rotate(${value('rotation')}deg)`, opacity: value('opacity')};
  return layer.type === 'video' ? <OffthreadVideo src={staticFile(layer.asset)} style={style} muted /> : <Img src={staticFile(layer.asset)} style={style} />;
};

export const NarratedVideo: React.FC<Plan> = (plan) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{backgroundColor: 'black', overflow: 'hidden'}}>
    {plan.shots.map((shot) => {
      const visible = frame >= shot.start_frame && frame < shot.start_frame + shot.duration_frames;
      if (!visible) return null;
      const style = mediaStyle(shot, frame, plan);
      const content = shot.type === 'video'
        ? <OffthreadVideo src={staticFile(shot.asset)} style={style} muted startFrom={Math.round((shot.source_start ?? 0) * plan.fps)} loop={shot.loop ?? false} />
        : <Img src={staticFile(shot.asset)} style={style} />;
      return <AbsoluteFill key={shot.id}>{content}{shot.layers.map((layer: any) => <Layer key={layer.id} layer={{...layer, _shot_start: shot.start_frame, _fps: plan.fps}} frame={frame} />)}</AbsoluteFill>;
    })}
  </AbsoluteFill>;
};
