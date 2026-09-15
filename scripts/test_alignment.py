import copy
import hashlib
import unittest
from alignment import validate_alignment, resolve_cue, map_asr_words


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.text='开，关，开。'
        self.data={'version':1,'audio_sha256':'audio','text_sha256':hashlib.sha256(self.text.encode()).hexdigest(),
            'provider':'fixture','revision':'1', 'spans':map_asr_words([
                {'word':t,'start':i*.5,'end':i*.5+.3,'probability':.9} for i,t in enumerate(['开','关','开'])], self.text)}

    def test_repeated_word_uses_character_interval(self):
        validate_alignment(self.data,self.text,'audio',2)
        self.assertEqual(resolve_cue({'char_start':4,'char_end':5,'text':'开'},self.data,self.text,30,90,60),60)

    def test_stale_audio_and_text(self):
        for text,audio in [(self.text,'new'),('关','audio')]:
            with self.assertRaises(ValueError):validate_alignment(self.data,text,audio,2)

    def test_no_guessed_asr_substitution(self):
        with self.assertRaises(ValueError):map_asr_words([{'word':'开开'}],self.text)

    def test_low_confidence_manual_and_missing_boundaries(self):
        cue={'char_start':0,'char_end':1,'text':'开'}
        data=copy.deepcopy(self.data);data['spans'][0]['confidence']=.1
        with self.assertRaises(ValueError):resolve_cue(cue,data,self.text,30,0,0)
        data=copy.deepcopy(self.data);data['spans'][0]['method']='manual'
        with self.assertRaises(ValueError):resolve_cue(cue,data,self.text,30,0,0)
        self.assertEqual(resolve_cue({**cue,'allow_manual':True},data,self.text,30,0,0),0)
        with self.assertRaises(ValueError):resolve_cue({**cue,'char_end':2},self.data,self.text,30,0,0)

    def test_invalid_time_revision_and_gaps(self):
        for update in [{'start':float('nan')},{'end':3},{'confidence':float('nan')}]:
            data=copy.deepcopy(self.data);data['spans'][0].update(update)
            with self.assertRaises(ValueError):validate_alignment(data,self.text,'audio',2)
        data=copy.deepcopy(self.data);data['revision']='latest'
        with self.assertRaises(ValueError):validate_alignment(data,self.text,'audio',2)
        data=copy.deepcopy(self.data);data['spans'].pop(1)
        with self.assertRaises(ValueError):resolve_cue({'char_start':0,'char_end':5,'text':self.text[:5]},data,self.text,30,0,0)


if __name__=='__main__':unittest.main()
