const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../src/multi_quest_teleop/webxr.html'),'utf8').split('<script>')[1].split('</script>')[0];
let nextFrame,session,draws=0,uploads=0;
const elements=Object.fromEntries(['token','operator','start','stop','status','view','server','certificate','video-enabled','video-status'].map(id=>[id,{value:'',removeAttribute(){}}]));
elements['video-enabled'].checked=true;
const gl=new Proxy({makeXRCompatible:async()=>{},getShaderParameter:()=>true,getProgramParameter:()=>true,
 drawArrays:()=>draws++,texImage2D:()=>uploads++},{get:(target,key)=>target[key] || (()=>({}))});
elements.view.getContext=()=>gl;
const video={readyState:2,videoWidth:640,videoHeight:480,play:async()=>{},pause(){}};
class Socket {
 static OPEN=1;static all=[];
 constructor(){this.readyState=1;this.sent=[];Socket.all.push(this);}
 send(raw){this.sent.push(JSON.parse(raw));}close(){this.readyState=3;}
}
class Peer {
 static all=[];
 constructor(){this.iceGatheringState='complete';Peer.all.push(this);}
 addTransceiver(kind,options){assert.equal(kind,'video');assert.equal(options.direction,'recvonly');}
 async createOffer(){return {type:'offer',sdp:'offer-sdp'};}
 async setLocalDescription(value){this.localDescription=value;}
 async setRemoteDescription(value){this.remoteDescription=value;}
 close(){this.closed=true;}
}
const context={document:{getElementById:id=>elements[id],createElement:()=>video},location:{hash:'#server=https%3A%2F%2F192.168.1.100%3A8443&token=secret',search:'',href:'https://host/',protocol:'https:',origin:'https://host'},
 URL,URLSearchParams,WebSocket:Socket,RTCPeerConnection:Peer,MediaStream:class{},isSecureContext:true,performance:{now:()=>0},setTimeout,clearTimeout,Float32Array,
 navigator:{xr:{requestSession:async kind=>{assert.equal(kind,'immersive-vr');return session={inputSources:[],addEventListener(){},updateRenderState(){},requestReferenceSpace:async()=>({addEventListener(){}}),requestAnimationFrame:cb=>nextFrame=cb,end:async()=>{}};}}},
 XRWebGLLayer:class{getViewport(){return {x:0,y:0,width:640,height:480};}},window:{addEventListener(){}}};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
 await elements.start.onclick();const socket=Socket.all[0];socket.onopen();await new Promise(setImmediate);
 assert.equal(socket.sent[0].type,'video_offer');
 socket.onmessage({data:JSON.stringify({type:'video_answer',sdp:'answer-sdp'})});
 assert.equal(Peer.all[0].remoteDescription.sdp,'answer-sdp');
 Peer.all[0].ontrack({track:{}});await new Promise(setImmediate);
 nextFrame(0,{getViewerPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}},views:[{},{}]})});
 assert.equal(draws,2);assert.equal(uploads,1);
 assert.deepEqual(Array.from(socket.sent[1].head),[1,2,3,0,0,0,1,1]);
 await elements.stop.onclick();assert.equal(Peer.all[0].closed,true);assert.equal(video.srcObject,null);
 console.log('PASS: WebRTC offer/answer, video playback, per-eye texture rendering, headset pose uplink, media cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
