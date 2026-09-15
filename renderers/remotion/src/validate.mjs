import {layerState,camera} from './animation.mjs';

const finite=(x)=>typeof x==='number'&&Number.isFinite(x);
const integer=(x)=>Number.isInteger(x)&&x>=0;
const boxOk=b=>b.every(finite)&&b[0]>=-1e-6&&b[1]>=-1e-6&&b[2]<=1+1e-6&&b[3]<=1+1e-6;
const overlap=(a,b)=>a[0]<b[2]&&b[0]<a[2]&&a[1]<b[3]&&b[1]<a[3];
export function validatePlan(plan){
  const errors=[],warnings=[],seen=new Set();let checked=0;
  const check=(ok,msg)=>{if(!ok)errors.push(msg);return ok;};
  if(!check(plan.version===1&&integer(plan.total_frames)&&plan.total_frames>0&&finite(plan.fps)&&plan.fps>0&&plan.fps<=120&&Number.isInteger(plan.width)&&plan.width>0&&Number.isInteger(plan.height)&&plan.height>0,'Invalid plan dimensions/timing'))return {status:'failed',errors};
  let cursor=0,previousTail=0;
  for(const shot of plan.shots){
    const prefix=shot.id+': ';
    check(!seen.has(shot.id),'Duplicate shot id');seen.add(shot.id);
    check(shot.start_frame===cursor&&shot.incoming_transition_frames===previousTail,prefix+'timeline/transition mismatch');
    check(integer(shot.spoken_frames)&&shot.spoken_frames>0&&integer(shot.transition_frames)&&shot.duration_frames===shot.spoken_frames+shot.transition_frames,prefix+'invalid duration');
    check(previousTail<=shot.spoken_frames,prefix+'incoming transition exceeds shot');
    previousTail=shot.transition_frames;cursor+=shot.spoken_frames;
    const ids=new Set();
    const media=item=>check(item.type!=='video'||(finite(item.source_duration)&&finite(item.source_start)&&item.source_start>=0&&item.source_start<item.source_duration),prefix+'invalid video source interval');
    media(shot);
    const graphics=shot.graphics||[],layers=shot.layers||[],e=shot.effects||{};
    check(Object.keys(e).every(k=>['vignette','light_sweep','particles'].includes(k)),prefix+'unknown effect');
    for(const k of ['vignette','light_sweep'])check(e[k]===undefined||(finite(e[k])&&e[k]>=0&&e[k]<=.5),prefix+k+' must be 0..0.5');
    check(e.particles===undefined||(integer(e.particles)&&e.particles<=80),prefix+'particles must be integer 0..80');
    for(const g of graphics){
      check(!ids.has(g.id)&&typeof g.id==='string',prefix+'duplicate/missing graphic id');ids.add(g.id);
      check(['selector','formula','nodes','coin'].includes(g.kind),prefix+'unknown graphic kind');
      check(finite(g.width)&&g.width>0&&finite(g.height)&&g.height>0&&boxOk([g.x,g.y,g.x+g.width,g.y+g.height]),prefix+g.id+' outside canvas');
      check(integer(g.start_frame)&&integer(g.end_frame)&&g.start_frame<g.end_frame&&g.end_frame<=shot.spoken_frames,prefix+g.id+' invalid visibility interval');
      check(g.kind==='coin'||(Array.isArray(g.items)&&g.items.length>0&&g.items.length<=12&&g.items.every(s=>typeof s==='string'&&s.length<=32)),prefix+g.id+' invalid items');
      let last=g.start_frame-1;
      for(const state of g.states||[]){
        check(integer(state.frame)&&state.frame>last&&state.frame>=g.start_frame&&state.frame<g.end_frame,prefix+g.id+' unsorted/hidden state');last=state.frame;
        check(['aligned','manual'].includes(state.timing_source),prefix+g.id+' missing event provenance');
        check(state.index===undefined||(integer(state.index)&&state.index<(g.items||[]).length),prefix+g.id+' index out of range');
        check(state.label===undefined||(typeof state.label==='string'&&state.label.length<=60),prefix+g.id+' label too long');
      }
      for(const label of g.required_labels||[])check((g.items||[]).includes(label)||g.label===label||(g.states||[]).some(s=>s.label===label),prefix+g.id+' missing required label '+label);
      for(const index of g.required_indices||[])check((g.states||[]).some(s=>s.index===index),prefix+g.id+' missing required state '+index);
    }
    for(const l of layers){
      check(!ids.has(l.id),prefix+'duplicate layer id');ids.add(l.id);media(l);
      check(l.depth===undefined||(finite(l.depth)&&Math.abs(l.depth)<=2),prefix+l.id+' depth must be -2..2');
      check(finite(l.start)&&finite(l.end)&&l.start>=0&&l.end>l.start&&l.end<=shot.spoken_frames/plan.fps+1e-6,prefix+l.id+' invalid layer interval');
      let last=-1;
      check(Array.isArray(l.keyframes)&&l.keyframes.length>0,prefix+l.id+' missing keyframes');
      for(const k of l.keyframes||[]){check(finite(k.time)&&k.time>last&&['x','y','scale','opacity','rotation'].every(p=>finite(k[p]))&&k.scale>0&&k.opacity>=0&&k.opacity<=1,prefix+l.id+' invalid keyframe');last=k.time;}
    }
    if(errors.length)continue;
    const failures=new Set();
    for(let f=0;f<shot.spoken_frames;f++){
      checked++;
      const boxes=graphics.filter(g=>g.start_frame<=f&&f<g.end_frame).map(g=>({id:g.id,box:[g.x,g.y,g.x+g.width,g.y+g.height],allow:g.allow_overlap_with||[]}));
      const cam=camera(shot.motion,f,shot.duration_frames,plan.motion?.max_zoom,plan.motion?.easing);
      for(const l of layers){
        const s=layerState(l,f/plan.fps);if(!s||s.opacity===0)continue;
        const r=s.rotation*Math.PI/180,w=(l.width??.3)*s.scale,h=(l.height??.3)*s.scale;
        // Rotation is in pixel space; normalized dimensions need aspect correction.
        const dx=(Math.abs(w*Math.cos(r))+Math.abs(h*Math.sin(r))*plan.height/plan.width)/2;
        const dy=(Math.abs(h*Math.cos(r))+Math.abs(w*Math.sin(r))*plan.width/plan.height)/2;
        const x=s.x+cam.x*(l.depth||0),b=[x-dx,s.y-dy,x+dx,s.y+dy];
        if(l.constrain_to_frame&&!boxOk(b))failures.add(l.id+' trajectory leaves canvas (first observed frame '+f+')');
        boxes.push({id:l.id,box:b,allow:l.allow_overlap_with||[],layer:true});
      }
      for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
        const a=boxes[i],b=boxes[j];
        if(a.layer&&b.layer)continue; // Layer compositing is intentional by default.
        if(!a.allow.includes(b.id)&&!b.allow.includes(a.id)&&overlap(a.box,b.box))failures.add('overlap '+a.id+'/'+b.id);
      }
    }
    for(const msg of failures)errors.push(prefix+msg);
    if(layers.some(l=>!l.constrain_to_frame))warnings.push(prefix+'unconstrained layers may leave canvas');
  }
  check(cursor===plan.total_frames&&previousTail===0,'Total frames/final transition mismatch');
  return {status:errors.length?'failed':'passed',errors,warnings,checked_frames:checked,
    coverage:['plan chronology','all state events','required labels/states','per-frame conservative geometry'],
    pending_review:['actual glyph readability and safe area','pronunciation and perceived sync','subject identity and narrative meaning']};
}
