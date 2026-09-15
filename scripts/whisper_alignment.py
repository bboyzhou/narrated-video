"""Optional Whisper ASR/attention-DTW alignment using an explicitly hashed model.

No download, transcript correction, guessed cues, or evenly divided word times.
Requires openai-whisper in the selected Python; does not install it.
"""
import argparse
import importlib.metadata
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from alignment import digest_file, map_asr_words, validate_alignment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request')
    parser.add_argument('output')
    args=parser.parse_args()
    request=json.loads(Path(args.request).read_text(encoding='utf-8'))
    model_path=Path(request['model_path'])
    if not model_path.is_absolute() or not model_path.is_file() or digest_file(model_path)!=request['model_sha256']:
        raise ValueError('Explicit local Whisper model/hash required')
    if importlib.metadata.version('openai-whisper')!=request['revision']:
        raise ValueError('Installed Whisper version differs from pinned revision')
    if request.get('tts_text',request['text'])!=request['text']:
        raise ValueError('Pronunciation proxy needs an explicit display/spoken mapping provider')
    if digest_file(request['audio'])!=request['audio_sha256']:
        raise ValueError('Audio changed after request creation')
    import numpy as np
    import whisper
    pcm=subprocess.run([request['ffmpeg'],'-v','error','-i',request['audio'],'-f','s16le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True,timeout=120).stdout
    model=whisper.load_model(str(model_path.resolve()),device=request.get('device','cpu'))
    audio=np.frombuffer(pcm,dtype=np.int16).astype(np.float32)/32768
    mode=request.get('mode','asr')
    if mode=='forced':
        # This is a version-specific internal API, never called on an untested revision.
        if request['revision']!='20231117':raise ValueError('Forced mode currently supports Whisper 20231117 only')
        from whisper.audio import N_SAMPLES, N_FRAMES, HOP_LENGTH
        from whisper.tokenizer import get_tokenizer
        from whisper.timing import find_alignment
        if not 0<len(audio)<=N_SAMPLES:raise ValueError('Forced mode requires a nonempty sentence of at most 30 seconds')
        model_name=request['model_name']
        if model_name not in whisper._MODELS or whisper._MODELS[model_name].split('/')[-2]!=request['model_sha256']:
            raise ValueError('Forced mode requires an official model hash and matching model_name')
        model.set_alignment_heads(whisper._ALIGNMENT_HEADS[model_name])
        tokenizer=get_tokenizer(model.is_multilingual,num_languages=model.num_languages,language=request.get('language','zh'),task='transcribe')
        tokens=tokenizer.encode(request['text'])
        if len(tokens)+len(tokenizer.sot_sequence)+2>model.dims.n_text_ctx:raise ValueError('Sentence exceeds model text context')
        mel=whisper.log_mel_spectrogram(audio,n_mels=model.dims.n_mels)
        mel=whisper.pad_or_trim(mel,N_FRAMES).to(model.device)
        words=[asdict(w) for w in find_alignment(model,tokenizer,tokens,mel,len(audio)//HOP_LENGTH)]
        for word in words:
            for field in ('start','end','probability'):word[field]=float(word[field])
        result={'text':request['text']}
    elif mode=='asr':
        result=model.transcribe(audio,language=request.get('language','zh'),word_timestamps=True,temperature=0,
            condition_on_previous_text=False,fp16=False)
        words=[w for segment in result['segments'] for w in segment.get('words',[])]
    else:raise ValueError('mode must be asr or forced')
    diagnostic={'audio_sha256':request['audio_sha256'],'model_sha256':request['model_sha256'],
                'revision':request['revision'],'mode':mode,'transcript':result['text'],'words':words}
    Path(args.output).with_suffix('.diagnostics.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
    data={k:request[k] for k in ('audio_sha256','text_sha256','revision','model_sha256')}
    data.update(version=1,provider='openai-whisper-'+mode,spans=map_asr_words(words,request['text']))
    if mode=='forced':
        for span in data['spans']:span['method']='forced'
    validate_alignment(data,request['text'],request['audio_sha256'],request['duration'])
    Path(args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
