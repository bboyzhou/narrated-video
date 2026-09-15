import test from 'node:test';
import assert from 'node:assert/strict';
import {camera,layerState,activeState} from '../src/animation.mjs';
import {validatePlan} from '../src/validate.mjs';
const key=(time,x)=>({time,x,y:.5,scale:1,rotation:0,opacity:1});
const layer={id:'L',start:.2,end:1,width:.1,height:.1,easing:'linear',keyframes:[key(0,.2),key(.3,.8),key(.8,.4)],constrain_to_frame:true};
const graphic={id:'G',kind:'selector',x:.1,y:.1,width:.8,height:.2,start_frame:0,end_frame:30,items:['0','1'],required_indices:[0,1],states:[{frame:0,index:0,timing_source:'manual'},{frame:20,index:1,timing_source:'manual'}]};
const plan=()=>({version:1,fps:30,width:320,height:180,total_frames:30,shots:[{id:'S',start_frame:0,spoken_frames:30,duration_frames:30,transition_frames:0,incoming_transition_frames:0,motion:'pan-left',type:'image',layers:[structuredClone(layer)],graphics:[structuredClone(graphic)]}]});
test('all keyframes and exclusive layer end',()=>{assert.equal(layerState(layer,.1),null);assert.equal(layerState(layer,1),null);assert.equal(layerState(layer,.5).x,.8);assert.ok(Math.abs(layerState(layer,.75).x-.6)<1e-9);});
test('camera remains covering canvas',()=>{for(const motion of ['push','pull','pan-left','pan-right','still'])for(let f=0;f<90;f++){const c=camera(motion,f,90);assert.ok(Math.abs(c.x)<=(c.scale-1)/2+1e-10);}});
test('state holds between events',()=>{assert.equal(activeState(graphic,19).index,0);assert.equal(activeState(graphic,20).index,1);});
test('valid plan checks every frame',()=>{const r=validatePlan(plan());assert.equal(r.status,'passed',JSON.stringify(r));assert.equal(r.checked_frames,30);});
test('missing state, hidden event, unsafe box and overlaps fail',()=>{
 for(const edit of [p=>p.shots[0].graphics[0].states.pop(),p=>p.shots[0].graphics[0].states[1].frame=30,p=>p.shots[0].graphics[0].x=.9,p=>p.shots[0].graphics[0].y=.45]){const p=plan();edit(p);assert.equal(validatePlan(p).status,'failed');}
});
test('middle trajectory and rotation are checked',()=>{const p=plan();p.shots[0].layers[0].keyframes[1].x=1.5;assert.equal(validatePlan(p).status,'failed');});
test('incoming tail belongs to preceding shot',()=>{const p=plan();p.shots[0].incoming_transition_frames=3;assert.equal(validatePlan(p).status,'failed');});
