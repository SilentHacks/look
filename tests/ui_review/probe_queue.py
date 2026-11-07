"""Pure real VoiceTurns recovery paths, no host bootstrap, CDP, models, or audio."""
import sys,json,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import tests
from tests.test_voice_turns import Chrome,Host,snapshot
from hermes_gaze.voice_turns import VoiceTurns
out={}
def state(t,h):return {'paused':t.paused,'host_refused':t.host_refused,'pending':[{'status':r['status'],'question':r['utterance']} for r in t.pending],'active':t.active and t.active['utterance'],'injections':len(h.messages)}
def rig():
 h=Host();t=VoiceTurns(h,Chrome());t.model_names=False;t.bind(session_key='k',session_id='s');return t,h
# Exactly the build note's "I didn't catch that", then ask again with successful transcription.
t,h=rig();a=t.capture(snapshot('first'),transcribing=True);t.transcribed(a['request_id'],'',error='No speech recognized');out['asr_failed']=state(t,h)
b=t.capture(snapshot('second'),transcribing=True);t.transcribed(b['request_id'],'Explain the second topic',snapshot('second'));out['asked_again']=state(t,h)
t.control('resume');out['resume_after_asr_failure']=state(t,h)
t.control('skip',a['item_id'],a['request_id']);out['skip_after_resume']=state(t,h)
t.close()
# A failed actual model turn does clear when the next question is accepted.
t,h=rig();a=t.submit('First',snapshot('first'));t.pre(session_id='s',turn_id='A',user_message=h.messages[-1][0]);t.end(session_id='s',turn_id='A',failed=True);t.submit('Second',snapshot('second'));out['new_after_model_failure']=state(t,h);t.close()
outpath=Path(os.environ.get('GAZE_REVIEW_OUT',str(Path(__file__).parent)))/'queue-results.json'
outpath.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
assert out['asr_failed']['pending'] == []
assert out['asked_again']['injections'] == out['resume_after_asr_failure']['injections'] == 1
assert out['asked_again']['active'] == 'Explain the second topic'
print('PASS F5: retained ASR failure does not block runnable work')
