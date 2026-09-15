"""Opt-in real Remotion + FFmpeg smoke; isolated synthetic fixtures only.

python scripts/test_remotion_smoke.py --ffmpeg PATH --browser PATH --node PATH --image PATH --output DIR
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from pipeline import Project, initialize, preflight_fingerprint, preflight_path, write_json, read_json
from test_pipeline import tone, storyboard_for
from alignment import prepare_requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('ffmpeg','browser','node','image','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    parent=Path(args.output).resolve();parent.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='remotion-',dir=parent));project=root/'project.json'
    initialize(project,None);c=read_json(project)
    c.update(output={'width':320,'height':180,'fps':30},voice={'engine':'files'},
             runtime={'node':args.node,'browser':args.browser,'ffmpeg':args.ffmpeg},
             renderer={'engine':'remotion','fallback':'none'})
    c['narration']=[{'id':f'N{i}','text':'开关。','audio':f'{i}.wav','alignment':f'{i}-alignment.json'} for i in range(1,4)]
    (root/'approved-script.txt').write_text('开关。'*3,encoding='utf-8')
    c['shots']=[{'id':f'S{i}','type':'video' if i<3 else 'image','asset':'source.mp4' if i<3 else 'image.png',
                 'narration':[f'N{i}'],'source_start':.1 if i<3 else 0,'loop':i==2,'motion':'pan-left' if i==3 else 'still',
                 'transition':.1*i,'prompt':'Synthetic smoke image','negative_prompt':'No watermark','source':'Test fixture'} for i in range(1,4)]
    cue=lambda a:{'sentence':'N1','char_start':a,'char_end':a+1,'text':'开关'[a],'allow_manual':True}
    c['shots'][0]['graphics']=[{'id':'switch','kind':'selector','x':.1,'y':.1,'width':.8,'height':.2,
        'start_frame':0,'end_frame':30,'items':['0','1'],'required_indices':[0,1],
        'states':[{'cue':cue(0),'index':0},{'cue':cue(1),'index':1}]}]
    c['shots'][1]['graphics']=[{'id':'formula','kind':'formula','x':.1,'y':.1,'width':.8,'height':.3,
        'start_frame':0,'end_frame':30,'items':['8','4','2','1'],'label':'1011 : 8 + 2 + 1 = 11',
        'required_labels':['8','4','2','1'],'states':[{'frame':0,'index':0,'timing_source':'manual'},{'frame':15,'index':2,'timing_source':'manual'}]}]
    c['shots'][2]['graphics']=[{'id':'coin','kind':'coin','x':.1,'y':.1,'width':.8,'height':.4,
        'start_frame':0,'end_frame':36,'states':[{'frame':0,'label':'0 / 1','timing_source':'manual'}]}]
    c['shots'][2]['effects']={'particles':8,'vignette':.15,'light_sweep':.1}
    key=lambda t,x:{'time':t,'x':x,'y':.75,'scale':1,'rotation':0,'opacity':1}
    c['shots'][1]['layers']=[{'id':'video-layer','type':'video','asset':'source.mp4','source_start':.1,'loop':True,
        'start':.2,'end':1,'width':.15,'height':.2,'depth':.5,'constrain_to_frame':True,
        'keyframes':[key(0,.2),key(.3,.8),key(.8,.5)]}]
    c['demo']={'shots':['S1','S2']}
    c['music']=[{'path':'music.wav','start':0,'end':8,'volume':.1,'source':'Synthetic 110Hz tone','license':'Test fixture'}]
    for i,d in enumerate([1.07,1.13,1.2],1):tone(root/f'{i}.wav',d,220*i)
    tone(root/'music.wav',1.5,110);shutil.copyfile(args.image,root/'image.png')
    subprocess.run([args.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30','-t','0.5','-c:v','libx264','-pix_fmt','yuv420p',str(root/'source.mp4')],check=True)
    storyboard=storyboard_for(c['shots'])
    for shot,plan in zip(c['shots'],storyboard['shots']):
        for k in ('type','source_start','loop','graphics','effects','layers'):
            if k in shot:plan[k]=shot[k]
    write_json(root/'storyboard.json',storyboard);write_json(project,c)
    write_json(preflight_path(project),{'ok':True,'fingerprint':preflight_fingerprint(project,c,args.ffmpeg),'test_fixture':True})
    p=Project(project,args.ffmpeg);p.record('script','TEST FIXTURE ONLY');p.record('storyboard','TEST FIXTURE ONLY')
    requests=prepare_requests(p,'demo')
    for i,request_path in enumerate(requests['requests'],1):
        request=read_json(request_path)
        write_json(root/f'{i}-alignment.json',{'version':1,'provider':'synthetic-fixture','revision':'1',
            'audio_sha256':request['audio_sha256'],'text_sha256':request['text_sha256'],
            'spans':[{'char_start':a,'char_end':a+1,'start':.1+a*.4,'end':.3+a*.4,'confidence':1,'method':'manual'} for a in range(2)]})
    p=Project(project,args.ffmpeg);p.render('demo');p.record('demo','TEST FIXTURE ONLY')
    requests=prepare_requests(p,'full')
    request=read_json(requests['requests'][2])
    write_json(root/'3-alignment.json',{'version':1,'provider':'synthetic-fixture','revision':'1',
        'audio_sha256':request['audio_sha256'],'text_sha256':request['text_sha256'],
        'spans':[{'char_start':0,'char_end':1,'start':.1,'end':.3,'confidence':1,'method':'manual'}]})
    p.render('full')
    report=read_json(root/'deliverables/full-verification.json')
    assert report['decoded_frames']==103,report
    assert read_json(root/'deliverables/full-renderer.json')['actual_renderer']=='remotion'
    qa=read_json(root/'deliverables/full-render-plan-qa.json');assert qa['status']=='passed',qa
    plan=read_json(root/'deliverables/full-render-plan.json')
    assert [s['frame'] for s in plan['shots'][0]['graphics'][0]['states']]==[3,15]
    p=Project(project,args.ffmpeg);p.render('full');assert p.stats['rendered']==0,p.stats
    voices=p.voices('full')
    # Corrupt alignment must be rejected, not replaced by guessed timing.
    bad=read_json(root/'1-alignment.json');bad['audio_sha256']='stale';write_json(root/'1-alignment.json',bad)
    try:p.build_render_plan('full',p.resolved_selected('full'),voices,plan['captions'])
    except ValueError as e:assert 'hash mismatch' in str(e)
    else:raise AssertionError('Stale alignment accepted')
    bad['audio_sha256']=read_json(requests['requests'][0])['audio_sha256'];write_json(root/'1-alignment.json',bad)
    for frame in [0,3,15,32,40,48,66,67,85,102]:
        subprocess.run([args.ffmpeg,'-v','error','-i',str(root/'deliverables/full.mp4'),'-vf',f'select=eq(n\\,{frame})','-frames:v','1',str(root/f'frame-{frame}.png')],check=True)
    write_json(root/'smoke-summary.json',{'status':'passed','frames':103,'cache':p.stats,'qa':qa,
        'limits':'Synthetic tones/manual fixture timestamps; not a speech recognition or subjective-sync evaluation'})
    print('SMOKE PASSED '+str(root))


if __name__=='__main__':main()
