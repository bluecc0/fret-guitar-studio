(function(root){
function finite(v){return typeof v==='number'&&Number.isFinite(v)}
function validatePart(part,initialBpm){
 if(!part||!Array.isArray(part.events)||!Array.isArray(part.measures)||!Array.isArray(part.tempos))throw Error('乐谱结构无效');
 if(part.events.length>20000)throw Error('音符数量过多，请分段练习');
 if(!part.events.length||!part.events.some(e=>!e.rest))throw Error('此声部没有可练习的音符');
 for(const e of part.events){if(!finite(e.beat)||e.beat<0||!finite(e.duration)||e.duration<=0)throw Error('音符起点或时值无效');if(!e.rest&&(!finite(e.midi)||e.midi<0||e.midi>127))throw Error('存在未确认音高，请校正后再练习')}
 for(const t of part.tempos)if(!finite(t.beat)||t.beat<0||!finite(t.bpm)||t.bpm<10||t.bpm>400)throw Error('速度标记无效');
 if(!part.tempos.some(t=>t.beat===0)&&!(finite(initialBpm)&&initialBpm>=10&&initialBpm<=400))throw Error('原谱没有起始速度，请先填写 BPM');
 for(const m of part.measures)if(!finite(m.numerator)||!finite(m.denominator)||m.numerator<=0||m.denominator<=0)throw Error('拍号缺失，请在校对中填写');
}
function timeline(part,initialBpm){validatePart(part,initialBpm);let tempos=part.tempos.map(t=>({...t}));if(!tempos.some(t=>t.beat===0))tempos.push({beat:0,bpm:initialBpm});tempos.sort((a,b)=>a.beat-b.beat);tempos=tempos.filter((t,i)=>!tempos[i+1]||tempos[i+1].beat!==t.beat);
 function seconds(beat){let total=0,last=0,bpm=tempos[0].bpm;for(const t of tempos){if(t.beat>beat)break;total+=(t.beat-last)*60/bpm;last=t.beat;bpm=t.bpm}return total+(beat-last)*60/bpm}
 const events=part.events.map(e=>({...e,start:seconds(e.beat),length:seconds(e.beat+e.duration)-seconds(e.beat)})).sort((a,b)=>a.start-b.start);
 const grouped=[];for(const e of events.filter(e=>!e.rest)){let g=grouped.at(-1);if(g&&Math.abs(g.start-e.start)<1e-6){g.notes.push(e);g.length=Math.max(g.length,e.length)}else grouped.push({start:e.start,length:e.length,beat:e.beat,notes:[e]})}
 return {events,groups:grouped,tempos,seconds,measures:part.measures.map(m=>({...m,start:seconds(m.beat)})),duration:Math.max(seconds(part.durationBeats||0),...events.map(e=>e.start+e.length))};
}
const api={timeline,validatePart};root.FretTimeline=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
