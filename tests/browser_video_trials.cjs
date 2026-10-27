const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../src/multi_quest_teleop/webxr.html'),'utf8').split('<script>')[1].split('</script>')[0];
let nextFrame,session,draws=0,uploads=0;const ranges=[],fits=[],matrices=[];
const elements=Object.fromEntries(['token','operator','start','stop','status','view','server','certificate','video-enabled','video-status'].map(id=>[id,{value:'',removeAttribute(){}}]));
elements['video-enabled'].checked=true;
const gl=new Proxy({makeXRCompatible:async()=>{},getShaderParameter:()=>true,getProgramParameter:()=>true,
 getUniformLocation:(_,name)=>name,
 uniform2f:(name,x,y)=>{if(name==='eyeRange')ranges.push([x,y]);if(name==='fit')fits.push([x,y]);},
 uniformMatrix4fv:(_,transpose,matrix)=>matrices.push(Array.from(matrix)),
 drawArrays:()=>draws++,texImage2D:()=>uploads++},{get:(target,key)=>target[key] || (()=>({}))});
elements.view.getContext=()=>gl;
const video={readyState:2,videoWidth:640,videoHeight:480,play:async()=>{},pause(){},requestVideoFrameCallback(callback){this.callback=callback;return 1;},cancelVideoFrameCallback(){}};
class Socket {
 static OPEN=1;static all=[];
 constructor(){this.readyState=1;this.sent=[];Socket.all.push(this);}
 send(raw){this.sent.push(JSON.parse(raw));}close(){this.readyState=3;}
}
class Peer {
 static all=[];
 constructor(){this.iceGatheringState='complete';Peer.all.push(this);}
 createDataChannel(){this.channel={};return this.channel;}
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
 video.callback(0,{rtpTimestamp:100});
 nextFrame(0,{getViewerPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}},views:[{},{}]})});
 assert.equal(draws,2);assert.equal(uploads,1);
 assert.deepEqual(Array.from(socket.sent[1].head),[1,2,3,0,0,0,1,1]);
 const projection=[1,0,0,0,0,1,0,0,0,0,-1,-1,0,0,-.1,0];
 socket.onmessage({data:JSON.stringify({ack:0,video:{layout:'stereo-sbs',projections:{left:projection,right:projection}}})});
 const eyeView=(eye,x)=>({eye,projectionMatrix:projection,transform:{position:{x,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}}});
 nextFrame(0,{getViewerPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}},views:[eyeView('left',.968),eyeView('right',1.032)]})});
 assert.deepEqual(ranges.slice(-2),[[0,.5],[.5,.5]]);
 assert.deepEqual(fits.slice(-2),[[1,1],[1,1]]); // cover each eye, no flat-screen letterboxing
 assert.equal(matrices.length,2);
 for(const matrix of matrices) for(let i=0;i<16;i++) assert.ok(Math.abs(matrix[i]-Number(i%5===0))<1e-6);
 assert.equal(socket.sent.at(-1).views.length,2);
 assert.equal(socket.sent.at(-1).views[0].eye,'left');
 assert.match(elements['video-status'].textContent,/320×480 per eye/);
 const yaw=10*Math.PI/180;
 // Metadata for a different decoded frame must never affect this texture.
 Peer.all[0].channel.onmessage({data:JSON.stringify({rtpTimestamp:99,video:{layout:'stereo-sbs',projections:{left:projection,right:projection},orientations:{left:[0,Math.sin(yaw/2),0,Math.cos(yaw/2)],right:[0,Math.sin(yaw/2),0,Math.cos(yaw/2)]}}})});
 nextFrame(0,{getViewerPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}},views:[eyeView('left',.968),eyeView('right',1.032)]})});
 assert.equal(vm.runInContext('videoRenderer.reprojecting',context),false);
 Peer.all[0].channel.onmessage({data:JSON.stringify({rtpTimestamp:100,video:{layout:'stereo-sbs',projections:{left:projection,right:projection},orientations:{left:[0,Math.sin(yaw/2),0,Math.cos(yaw/2)],right:[0,Math.sin(yaw/2),0,Math.cos(yaw/2)]}}})});
 nextFrame(0,{getViewerPose:()=>({transform:{position:{x:1,y:2,z:3},orientation:{x:0,y:0,z:0,w:1}},views:[eyeView('left',.968),eyeView('right',1.032)]})});
 assert.equal(vm.runInContext('videoRenderer.reprojecting',context),true);
 const warped=matrices.at(-1);assert.ok(Math.abs((warped[8]+warped[12])/(warped[11]+warped[15])-Math.tan(yaw))<1e-5);
 const asymmetric=projection.slice();asymmetric[8]=.2;asymmetric[9]=-.1;
 const remap=vm.runInContext(`projectionMap(${JSON.stringify(projection)},${JSON.stringify(asymmetric)})`,context);
 assert.ok(Math.abs(remap[12]-.2)<1e-6);assert.ok(Math.abs(remap[13]+.1)<1e-6);
 await elements.stop.onclick();assert.equal(Peer.all[0].closed,true);assert.equal(video.srcObject,null);
 console.log('PASS: WebRTC offer/answer, video playback, per-eye texture rendering, headset pose uplink, media cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
