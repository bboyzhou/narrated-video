import React from 'react';
import {AbsoluteFill,Img,OffthreadVideo,Sequence,Loop,Freeze,staticFile,useCurrentFrame} from 'remotion';
import {camera,layerState,clamp} from './animation.mjs';
import {Graphic,Effects} from './graphics';
type Plan={width:number;height:number;fps:number;total_frames:number;shots:any[];motion?:any};
const Media:React.FC<{item:any;fps:number;style:React.CSSProperties}>=({item,fps,style})=>{
  const frame=useCurrentFrame();
  if(item.type!=='video')return <Img src={staticFile(item.asset)} style={style}/>;
  const offset=Math.round((item.source_start||0)*fps),total=Math.max(1,Math.floor(item.source_duration*fps)),first=Math.max(1,total-offset);
  const video=<OffthreadVideo src={staticFile(item.asset)} style={style} muted startFrom={offset}/>;
  if(frame<first)return video;
  if(item.loop)return <Sequence from={first}><Loop durationInFrames={total}><OffthreadVideo src={staticFile(item.asset)} style={style} muted/></Loop></Sequence>;
  return <Freeze frame={first-1}>{video}</Freeze>;
};
const Shot:React.FC<{shot:any;plan:Plan}>=({shot,plan})=>{
  const frame=useCurrentFrame(),cam=camera(shot.motion,frame,shot.duration_frames,plan.motion?.max_zoom,plan.motion?.easing);
  const opacity=shot.incoming_transition_frames?clamp(frame/shot.incoming_transition_frames):1;
  return <AbsoluteFill style={{opacity,overflow:'hidden'}}>
    <Media item={shot} fps={plan.fps} style={{width:'100%',height:'100%',objectFit:'cover',transform:`translateX(${cam.x*100}%) scale(${cam.scale})`}}/>
    {shot.layers.map((layer:any)=>{
      const s=layerState(layer,frame/plan.fps);if(!s||frame>=shot.spoken_frames)return null;
      return <Sequence key={layer.id} from={Math.ceil(layer.start*plan.fps)} durationInFrames={Math.max(1,Math.ceil(layer.end*plan.fps)-Math.ceil(layer.start*plan.fps))} layout="none">
        <Media item={layer} fps={plan.fps} style={{position:'absolute',left:`${(s.x+cam.x*(layer.depth||0))*100}%`,top:`${s.y*100}%`,width:`${(layer.width??.3)*100}%`,height:`${(layer.height??.3)*100}%`,objectFit:'contain',transform:`translate(-50%,-50%) scale(${s.scale}) rotate(${s.rotation}deg)`,opacity:s.opacity}}/>
      </Sequence>;
    })}
    {(shot.graphics||[]).map((g:any)=><Graphic key={g.id} component={g} frame={frame} fps={plan.fps}/>)}
    <Effects effects={shot.effects||{}} frame={frame} fps={plan.fps}/>
  </AbsoluteFill>;
};
export const NarratedVideo:React.FC<Plan>=plan=><AbsoluteFill style={{backgroundColor:'black',overflow:'hidden'}}>{plan.shots.map(shot=><Sequence key={shot.id} from={shot.start_frame} durationInFrames={shot.duration_frames}><Shot shot={shot} plan={plan}/></Sequence>)}</AbsoluteFill>;
