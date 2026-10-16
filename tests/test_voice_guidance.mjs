import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {guidanceFor, VoiceGuide} from '../hmi/guidance.js';

const manifest=JSON.parse(await readFile(new URL('../hmi/audio/prompts.json',import.meta.url),'utf8'));
const services=JSON.parse(await readFile(new URL('../config/services.json',import.meta.url),'utf8')).services;
const missions=JSON.parse(await readFile(new URL('../config/solutions.json',import.meta.url),'utf8')).missions;
const snap={state:'ACTIVE',mode:'GUIDED',session_id:'s',round_id:'r',step_epoch:1,buttons:services,panels:{13:'TARGET_HINT'},role_hint:{zh:'语音转文字',en:'Speech to text'}};
const guide=guidanceFor(snap);
assert.equal(guide.audioId,'service_transcribe');
assert.match(guide.title,/Transcribe/);
assert.equal(guidanceFor({...snap,panels:{2:'TARGET_HINT',13:'TARGET_HINT'},graph:{nodes:[{required:true,state:'ready',service:'TRANSCRIBE'},{required:true,state:'ready',service:'S3'}]}}).audioId,'service_transcribe','follow the displayed role order when several branches are ready');
assert.equal(guidanceFor({...snap,mode:'RUSH60_RANKED'}).audioId,'go');
assert.equal(guidanceFor({...snap,paused:true}).audioId,'paused');
assert.equal(guidanceFor({...snap,forfeit_pending:true}).audioId,'forfeit');
for(const service of services.filter(s=>s.id)){
  const g=guidanceFor({...snap,panels:{[service.id]:'TARGET_HINT'}});
  assert.ok(manifest.prompts.some(p=>p.id===g.audioId),g.audioId);
}
for(const mission of missions.filter(m=>m.ranked)){
  const g=guidanceFor({state:'MISSION_SELECT',menu_mission_id:mission.id});
  assert.ok(manifest.prompts.some(p=>p.id===g.audioId),g.audioId);
}
for(const p of manifest.prompts) for(const lang of ['zh','en']){
  assert.ok(p[lang].text && p[lang].file);
  assert.doesNotMatch(p[lang].text,/第十七|第\s*17|seventeen|button 17/i);
}
let plays=0;
const audio={pause(){},async play(){plays++;}};
const player=new VoiceGuide({manifest,enabled:true,storage:null,audioFactory:()=>audio});
player.update(guide); await new Promise(r=>setTimeout(r,0));
assert.equal(plays,1);
assert.equal(audio.src,'/audio/zh/service_transcribe.mp3');
player.update(guide); await new Promise(r=>setTimeout(r,0));
assert.equal(plays,1,'snapshot polling must not repeat speech');
player.update(guidanceFor({...snap,step_epoch:2})); await new Promise(r=>setTimeout(r,0));
assert.equal(plays,2,'new step must speak even when service repeats');
player.update(guide,'en'); await new Promise(r=>setTimeout(r,0));
assert.equal(audio.src,'/audio/en/service_transcribe.mp3');
player.destroy();

// Completion narration queues navigation, stays silent during the race, and is cancellable.
for (const mission of missions) for (const lang of ['zh','en']) {
  const result = guidanceFor({state:'RESULT',mode:'GUIDED',session_id:'done',final_state:'VALID',mission,visit_remaining:2},lang);
  assert.equal(result.audioId, `solution_${mission.id.toLowerCase()}`);
  assert.ok(manifest.prompts.find(p=>p.id===result.audioId)?.[lang]?.file);
  assert.equal(result.audioIds[1],'guided_complete');
}
const last = guidanceFor({state:'RESULT',mode:'FREE',session_id:'last',final_state:'VALID',mission:missions[0],visit_remaining:0});
assert.equal(last.audioIds[1],'visit_done','third play explains before asking the visitor to leave');
const failed = guidanceFor({state:'RESULT',mode:'GUIDED',failure:{reason:'WRONG_SERVICE'},mission:missions[0]});
assert.equal(failed.audioId,'failed','a failed workflow must not be described as completed');
const race = {...snap,mode:'RUSH60_RANKED',last_completed_graph:{id:missions[0].id}};
assert.equal(guidanceFor(race).audioId,'go','no long narration over a live race');
assert.equal(guidanceFor({...race,state:'RESULT',final_state:'VALID'}).audioIds[0],'solution_m01_voice');
const queueAudio={pause(){},async play(){}};
const queue=new VoiceGuide({manifest,enabled:true,storage:null,audioFactory:()=>queueAudio});
queue.update(last); await new Promise(r=>setTimeout(r,0));
assert.equal(queueAudio.src,'/audio/zh/solution_m01_voice.mp3');
queueAudio.onended(); await new Promise(r=>setTimeout(r,0));
assert.equal(queueAudio.src,'/audio/zh/visit_done.mp3');
queue.update(last); await new Promise(r=>setTimeout(r,0));
assert.equal(queueAudio.src,'/audio/zh/visit_done.mp3','polling cannot restart narration');
await queue.replay();
assert.equal(queueAudio.src,'/audio/zh/solution_m01_voice.mp3');
const staleEnd=queueAudio.onended;
queue.update(guidanceFor({state:'MODE_LOBBY',mode:'FREE'})); await new Promise(r=>setTimeout(r,0));
staleEnd(); await new Promise(r=>setTimeout(r,0));
assert.equal(queueAudio.src,'/audio/zh/mode_free.mp3','leaving the result cancels the old playlist');
queue.destroy();
console.log('Voice guidance checks passed: target names, bilingual assets, no ranked answers, no polling replay.');
