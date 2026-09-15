import React from 'react';
import {activeState,clamp} from './animation.mjs';
export const Graphic:React.FC<{component:any;frame:number;fps:number}>=({component:g,frame,fps})=>{
  if(frame<g.start_frame||frame>=g.end_frame)return null;
  const state=activeState(g,frame),index=state?.index??-1,items=g.items||[],color=g.color||'#ffc857';
  const toss=clamp((frame-g.start_frame)/Math.max(1,Math.min(fps*2,g.end_frame-g.start_frame-1)));
  return <svg data-graphic-id={g.id} viewBox="0 0 1000 300" style={{position:'absolute',left:`${g.x*100}%`,top:`${g.y*100}%`,width:`${g.width*100}%`,height:`${g.height*100}%`,overflow:'hidden'}}>
    <rect x="0" y="0" width="1000" height="300" rx="18" fill="#061522" fillOpacity=".9"/>
    {g.kind==='coin'?<g transform={`translate(500,${110-60*4*toss*(1-toss)})`}><ellipse rx={Math.max(8,55*Math.abs(Math.cos(toss*Math.PI*6)))} ry="45" fill={color}/><text textAnchor="middle" y="12" fontSize="32">{state?.label||'0 / 1'}</text></g>:items.map((label:string,i:number)=>{const w=900/items.length,x=50+i*w;return <g key={i}>
      {g.kind==='nodes'&&i<items.length-1&&<line x1={x+w*.8} y1="100" x2={x+w*1.2} y2="100" stroke={color} strokeWidth="4"/>}
      <rect x={x+8} y="50" width={w-16} height="100" rx="10" fill={i===index?'#624500':'#142b40'} stroke={i===index?color:'#7794ab'} strokeWidth="4"/>
      <text x={x+w/2} y="110" textAnchor="middle" fill="white" fontSize={Math.min(40,w/(Math.max(1,label.length)*.8))}>{label}</text></g>;})}
    <text x="500" y="250" textAnchor="middle" fill="white" fontSize="30">{state?.label||g.label||''}</text>
  </svg>;
};
export const Effects:React.FC<{effects:any;frame:number;fps:number}>=({effects:e,frame,fps})=><>
  {e.vignette>0&&<div style={{position:'absolute',inset:0,background:`radial-gradient(ellipse, transparent 45%, rgba(0,0,0,${e.vignette}))`,pointerEvents:'none'}}/>}
  {e.light_sweep>0&&<div style={{position:'absolute',inset:0,opacity:e.light_sweep,background:`linear-gradient(110deg, transparent ${((frame/fps*12)%150)-40}%, #fff8 ${((frame/fps*12)%150)-20}%, transparent ${(frame/fps*12)%150}%)`,pointerEvents:'none'}}/>}
  {e.particles>0&&<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" style={{position:'absolute',inset:0,width:'100%',height:'100%',pointerEvents:'none'}}>{Array.from({length:e.particles},(_,i)=><circle key={i} cx={(i*137+frame*.35)%1000} cy={(i*211-frame*.2+100000)%1000} r={1+i%3} fill="#ffdfa0" opacity=".25"/>)}</svg>}
</>;
