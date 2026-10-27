// Run the actual page script against mocked WebXR, WebGL, and WebSocket APIs.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync(require('node:path').join(__dirname, '../src/multi_quest_teleop/webxr.html'),'utf8').split('<script>')[1].split('</script>')[0];
let now = 0, nextFrame, currentSession;
const elements = Object.fromEntries(['token','operator','start','stop','status','view','server','certificate'].map(id=>[id,{value:'',removeAttribute(){}}]));
const gl = {makeXRCompatible:async()=>{},bindFramebuffer(){},clearColor(){},clear(){}};
elements.view.getContext=()=>gl;
class Socket {
  static OPEN=1; static all=[];
  constructor(url){this.url=url;this.readyState=1;this.sent=[];Socket.all.push(this);}
  close(){this.readyState=3;}
  send(raw){this.sent.push(JSON.parse(raw));}
}
function makeSession(){
  const listeners={};
  return {listeners,visibilityState:'visible',inputSources:[],addEventListener:(name,cb)=>listeners[name]=cb,
    updateRenderState(){},requestReferenceSpace:async()=>({addEventListener:(n,cb)=>listeners['space:'+n]=cb}),
    requestAnimationFrame:cb=>nextFrame=cb,end:async()=>{}};
}
const context={document:{getElementById:id=>elements[id]},location:{search:'',hash:'#server=https%3A%2F%2F192.168.1.100%3A8443&token=secret&operator=b',href:'https://lakshyajain06.github.io/Multi-Quest-Teleop/',protocol:'https:',hostname:'lakshyajain06.github.io',origin:'https://lakshyajain06.github.io'},
  URL,URLSearchParams,WebSocket:Socket,isSecureContext:true,performance:{now:()=>now},
  navigator:{xr:{requestSession:async()=>currentSession=makeSession()}},XRWebGLLayer:class{},window:{addEventListener(){}}};
vm.createContext(context);vm.runInContext(script,context);
const frame={getPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}}})};
(async()=>{
  assert.equal(elements.operator.value,'b');
  await elements.start.onclick();
  let socket=Socket.all.at(-1);socket.onopen();
  assert.equal(socket.url.hostname,'192.168.1.100');
  assert.equal(elements.certificate.href,'https://192.168.1.100:8443/certificate');
  assert.equal(socket.url.protocol,'wss:');assert.equal(socket.url.searchParams.get('operator'),'b');
  currentSession.inputSources=[{handedness:'right',gripSpace:{},gamepad:{mapping:'xr-standard',buttons:[{value:.2},{value:.8},{},{pressed:true},{pressed:true},{pressed:false}],axes:[0,0,.3,-.4]}}];
  nextFrame(0,frame);
  assert.equal(socket.sent.length,1);
  assert.deepEqual(Array.from(socket.sent[0].controllers[1]),[1,2,3,0,0,0,1,.2,.8,1,1,0,1,.3,-.4]);
  nextFrame(0,frame);assert.equal(socket.sent.length,1); // one in flight
  socket.onmessage({data:'{"ack":99}'});nextFrame(0,frame);assert.equal(socket.sent.length,1);
  socket.onmessage({data:'{"ack":0}'});
  nextFrame(0,{getPose:()=>null});assert.equal(socket.sent[1].controllers[1][9],0);
  now=600;nextFrame(0,frame);assert.equal(socket.readyState,3);assert.match(elements.status.textContent,/stalled/);
  await elements.start.onclick();const fresh=Socket.all.at(-1);
  socket.onclose({reason:'old connection'});assert.equal(fresh.readyState,1);
  currentSession.listeners['space:reset']();assert.equal(fresh.readyState,3);
  await elements.start.onclick();socket=Socket.all.at(-1);
  currentSession.visibilityState='hidden';currentSession.listeners.visibilitychange();assert.equal(socket.readyState,3);
  context.isSecureContext=false;await elements.start.onclick();assert.match(elements.status.textContent,/HTTPS/);
  console.log('PASS: page initialization, secure URL, controller mapping, ACK backpressure, missing tracking, stalled link, reconnect race, origin reset, backgrounding, insecure context');
})().catch(error=>{console.error(error);process.exitCode=1;});
