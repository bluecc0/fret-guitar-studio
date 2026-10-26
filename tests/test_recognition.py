import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from backend.musicxml import parse_musicxml, ScoreError
from backend.server import app
from backend import vlm

FIXTURE=Path(__file__).parent/'fixtures/rhythm.musicxml'
class RecognitionTests(unittest.TestCase):
 def test_rhythm_preserved(self):
  s=parse_musicxml(FIXTURE.read_bytes());p=s['parts'][0]
  self.assertEqual(p['measures'][0]['duration'],.5)
  self.assertEqual([m['beat'] for m in p['measures']],[0,.5,4.5])
  self.assertEqual([t['bpm'] for t in p['tempos']],[120,60])
  self.assertEqual(p['events'][1]['duration'],1.5)
  self.assertEqual(p['events'][1]['beat'],p['events'][2]['beat'])
  tied=next(e for e in p['events'] if e['midi']==67)
  self.assertEqual(tied['duration'],3)
  self.assertEqual(len([e for e in p['events'] if e['midi']==67]),1)
  self.assertAlmostEqual(next(e for e in p['events'] if e['midi']==69)['duration'],1/3)
  self.assertTrue(any(e['rest'] for e in p['events']))
  self.assertEqual(p['harmonies'][0]['root'],'C')
  self.assertEqual(p['events'][0]['string'],1)
  self.assertFalse(p['warnings'])
 def test_missing_tempo_not_invented(self):
  data=FIXTURE.read_bytes().replace(b'<sound tempo="120"/>',b'')
  p=parse_musicxml(data)['parts'][0]
  self.assertFalse(any(t['beat']==0 for t in p['tempos']))
  self.assertTrue(any('BPM' in w for w in p['warnings']))
 def test_mxl(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:
   z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>');z.writestr('score.xml',FIXTURE.read_bytes())
  self.assertEqual(parse_musicxml(b.getvalue())['title'],'节奏校验谱')
 def test_entities_rejected(self):
  with self.assertRaises(ScoreError):parse_musicxml(b'<!DOCTYPE x [<!ENTITY test "boom">]><score-partwise/>')
 def test_api_xml_and_disabled_vlm(self):
  with TestClient(app) as client:
   r=client.post('/api/recognitions',files={'file':('test.musicxml',FIXTURE.read_bytes(),'application/xml')})
   self.assertEqual(r.status_code,202)
   for i in range(100):
    result=client.get('/api/recognitions/'+r.json()['id']).json()
    if result['status'] in ('completed','failed'):break
    time.sleep(.01)
   self.assertEqual(result['status'],'completed',result)
   with patch.dict(os.environ,{'VLM_API_KEY':'','VLM_MODEL':''}):
    h=client.get('/api/health').json();self.assertFalse(h['vlm']['configured'])
    r=client.post('/api/recognitions',files={'file':('a.png',b'\x89PNGxxxx','image/png')},data={'engine':'vlm'})
    self.assertEqual(r.status_code,503)
   self.assertEqual(client.get('/api/health',headers={'Origin':'https://untrusted.example'}).status_code,403)
 def test_audiveris_command_and_temp_cleanup(self):
  import backend.server as server
  with tempfile.TemporaryDirectory() as d:
   fake=Path(d)/'Audiveris';fake.write_text('#!/bin/sh\n');fake.chmod(0o755)
   command=[]
   def run(args,**kwargs):
    command.extend(args);out=Path(args[args.index('-output')+1]);(out/'recognized.musicxml').write_bytes(FIXTURE.read_bytes())
    return type('Process',(),{'returncode':0})()
   jid='test-audiveris';server.jobs[jid]={'created':time.time(),'status':'queued'}
   with patch.dict(os.environ,{'AUDIVERIS_BIN':str(fake)}),patch('backend.server.subprocess.run',side_effect=run):server.worker(jid,b'fake png','.png','audiveris')
   self.assertEqual(server.jobs[jid]['status'],'completed')
   self.assertIn('-transcribe',command);self.assertIn('-export',command)
   self.assertFalse(Path(command[-1]).exists())
 def test_openai_protocol_offline_contract(self):
  received={}
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return json.dumps({'choices':[{'message':{'content':json.dumps({'musicxml':FIXTURE.read_text(),'warnings':['核对三连音']})}}]}).encode()
  def request(req,**kwargs):received['url']=req.full_url;received['body']=json.loads(req.data);return Response()
  with patch.dict(os.environ,{'VLM_API_KEY':'offline-test-only','VLM_MODEL':'future-vision','VLM_BASE_URL':'https://vision.example/v1'}),patch('urllib.request.urlopen',side_effect=request):
   answer=vlm.transcribe([(b'test','image/png')])
  self.assertEqual(received['url'],'https://vision.example/v1/chat/completions')
  self.assertEqual(received['body']['model'],'future-vision')
  self.assertEqual(received['body']['messages'][1]['content'][1]['type'],'image_url')
  self.assertIn('score-partwise',answer['musicxml'])
if __name__=='__main__':unittest.main()
