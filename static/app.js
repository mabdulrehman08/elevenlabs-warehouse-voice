const $ = id => document.getElementById(id);
let context = {}, running = false, busy = false, stream, audioContext, audio, recorder, captureTimer;
let generation = 0;
const state = text => { $('state').textContent = text; $('dot').classList.toggle('live', running); };
function message(text, who, meta) {
  const node = document.createElement('div'); node.className = `message ${who}`; node.textContent = text;
  if (meta) { const detail = document.createElement('small'); detail.textContent = meta; node.append(detail); }
  $('messages').append(node); $('messages').scrollTop = $('messages').scrollHeight;
}
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request could not be processed. Try a shorter query.');
  return data;
}
async function turn(text) {
  if (busy) return;
  busy = true; $('send').disabled = true; $('error').textContent = ''; state('Looking up inventory…');
  const token = generation;
  message(text, 'user');
  try {
    const data = await api('/api/query', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text, context, speak:true}) });
    if (token !== generation) return;
    context = data.context;
    message(data.reply, 'agent', `${data.status.toUpperCase()} · ${data.elapsed_ms} ms · ${data.request_id}`);
    if (data.voice_error) { $('error').textContent = data.voice_error; if (running) end(); }
    if (data.audio) {
      state('Speaking…'); audio = new Audio(`data:audio/mpeg;base64,${data.audio}`);
      await new Promise((resolve, reject) => { audio.onended=resolve; audio.onerror=()=>reject(new Error('Audio playback failed. Read the answer above.')); audio.onpause=resolve; audio.play().catch(()=>reject(new Error('Playback was blocked. Click Start to enable audio.'))); });
    }
  } catch (error) { $('error').textContent = error.message; if (running) end(); }
  finally { busy=false; $('send').disabled=false; if (running) listen(); else state('Ready · typed queries available'); }
}
function end() {
  running=false; generation++; clearTimeout(captureTimer);
  if (recorder?.state === 'recording') { recorder.onstop=null; recorder.stop(); }
  stream?.getTracks().forEach(track=>track.stop());
  if (audioContext && audioContext.state !== 'closed') audioContext.close();
  audio?.pause(); $('start').hidden=false; $('stop').hidden=true; state('Session ended · microphone off');
}
function listen() {
  if (!running || busy) return;
  state('Listening · speak your query');
  const source = audioContext.createMediaStreamSource(stream), analyser = audioContext.createAnalyser();
  analyser.fftSize=1024; source.connect(analyser);
  const samples=new Float32Array(analyser.fftSize), chunks=[];
  const mime=['audio/webm','audio/ogg','audio/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
  if (!mime) { $('error').textContent='This browser cannot record supported audio. Use Chrome or typed queries.'; end(); return; }
  recorder=new MediaRecorder(stream,{mimeType:mime});
  const current = recorder, token=generation;
  let began=performance.now(), lastVoice=began, speech=false;
  current.ondataavailable=event=>{ if(event.data.size) chunks.push(event.data); };
  current.onstop=async()=>{
    source.disconnect();
    if (!running || token!==generation) return;
    if (!speech) { listen(); return; }
    busy=true; $('send').disabled=true; state('Transcribing with ElevenLabs…');
    try {
      const form=new FormData(); form.append('file',new Blob(chunks,{type:mime}),`query.${mime.split('/')[1]}`);
      const data=await api('/api/transcribe',{method:'POST',body:form});
      busy=false; if(running && token===generation) await turn(data.text);
    } catch(error) { busy=false; $('error').textContent=error.message; end(); }
    finally { $('send').disabled=false; }
  };
  current.start();
  function sample() {
    if (!running || current.state!=='recording') { source.disconnect(); return; }
    analyser.getFloatTimeDomainData(samples);
    const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length), now=performance.now();
    if(rms>0.035) { speech=true; lastVoice=now; }
    if ((speech && now-lastVoice>1100) || now-began>12000) { current.stop(); return; }
    captureTimer=setTimeout(sample,80);
  }
  sample();
}
$('start').onclick=async()=>{
  if (busy) return;
  $('error').textContent='';
  try {
    if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Microphone requires a supported browser on localhost or HTTPS. Typed queries are available.');
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    audioContext=new AudioContext(); await audioContext.resume(); running=true; generation++;
    $('start').hidden=true; $('stop').hidden=false; listen();
  } catch(error) { $('error').textContent=error.name==='NotAllowedError'?'Microphone permission denied. Allow microphone access, or type your query.':error.message; end(); }
};
$('stop').onclick=end;
$('form').onsubmit=event=>{ event.preventDefault(); if(running) end(); const text=$('query').value.trim(); if(text){$('query').value='';turn(text);} };
document.querySelectorAll('.example').forEach(button=>button.onclick=()=>{if(busy)return; if(running)end();turn(button.textContent);});
window.addEventListener('pagehide',end);
api('/api/status').then(data=>{ $('snapshot').textContent=new Date(data.snapshot).toUTCString(); state(data.voice_configured?'Voice configured · ready':'Text ready · voice key needed'); }).catch(error=>{state('Connection unavailable');$('error').textContent=error.message;});
