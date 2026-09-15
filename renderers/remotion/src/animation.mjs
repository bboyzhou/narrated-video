export const clamp = x => Math.max(0, Math.min(1, x));
export const easing = (x, mode='smoothstep') => mode==='linear' ? clamp(x) : clamp(x)**2*(3-2*clamp(x));
export function layerState(layer, seconds) {
  if(seconds<layer.start || seconds>=layer.end) return null;
  const time=seconds-layer.start, keys=layer.keyframes;
  let a=keys[0], b=a;
  for(let i=1;i<keys.length;i++){b=keys[i];if(time<=b.time)break;a=b;}
  const p=b.time===a.time?0:easing((time-a.time)/(b.time-a.time),layer.easing);
  return Object.fromEntries(['x','y','scale','rotation','opacity'].map(k=>[k,a[k]+(b[k]-a[k])*p]));
}
export function camera(motion,frame,duration,maxZoom=0.06,mode='smoothstep') {
  const p=easing(frame/Math.max(1,duration-1),mode);
  const scale=motion==='push'?1+maxZoom*p:motion==='pull'?1+maxZoom*(1-p):motion.startsWith('pan-')?1+maxZoom/2:1;
  const x=motion==='pan-left'?(scale-1)*(0.5-p):motion==='pan-right'?(scale-1)*(p-0.5):0;
  return {scale,x};
}
export const activeState=(component,frame)=>[...(component.states||[])].reverse().find(s=>s.frame<=frame)||null;
