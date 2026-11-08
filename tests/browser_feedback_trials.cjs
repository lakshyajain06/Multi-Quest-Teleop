// Exercise production feedback without a headset; transport is covered separately.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'../src/multi_quest_teleop/feedback.js'),'utf8'));
const feedback=createContactFeedback(), events=[];
const left={pulse:(a,d)=>{events.push(['left',a,d]);return Promise.resolve(true);}};
const right={pulse:(a,d)=>{events.push(['right',a,d]);return Promise.resolve(true);}};
const session={visibilityState:'visible',inputSources:[
 {handedness:'left',gamepad:{hapticActuators:[left]}},
 {handedness:'right',gamepad:{hapticActuators:[right]}}]};
assert.equal(feedback.update(session,0),0); // Older servers send no feedback.
const sample={version:1,seq:1,haptics:{left:.4,right:0},self_collision:true};
feedback.receive(sample,0);assert(feedback.update(session,1)>0);
assert.deepEqual(events,[['left',.4,80]]);
feedback.update(session,30);assert.equal(events.length,1);
feedback.update(session,80);assert.equal(events.length,2);
feedback.receive(sample,240); // Repeated ACKs cannot renew a stopped simulation.
feedback.update(session,251);assert.deepEqual(events.at(-1),['left',0,1]);
feedback.receive({version:1,seq:2,haptics:{left:0,right:100},self_collision:false},260);
feedback.update(session,261);assert.deepEqual(events.at(-1),['right',.65,80]);
session.visibilityState='hidden';feedback.update(session,270);
assert.deepEqual(events.at(-1),['right',0,1]);
session.visibilityState='visible';feedback.reset(session);assert.equal(feedback.update(session,271),0);
// Optional actuators and rejected browser promises never break input/video.
session.inputSources=[{handedness:'left',gamepad:{}},
 {handedness:'right',gamepad:{hapticActuators:[{pulse:()=>Promise.reject(Error('unsupported'))}]}}];
feedback.receive({version:1,seq:1,haptics:{left:.2,right:.2},self_collision:false},300);
feedback.update(session,301);
feedback.receive({version:1,seq:2,haptics:{left:NaN,right:Infinity},self_collision:false},310);
feedback.update(session,311);
// A single explicit test pulse isolates browser support from simulation forces.
const rumble=[];
session.inputSources=[{handedness:'left',gamepad:{vibrationActuator:{playEffect:(type,options)=>{
 rumble.push([type,options]);return Promise.resolve('complete');}}}}];
feedback.reset(session);rumble.length=0;feedback.startTest(400);
assert(feedback.update(session,401)>0);
assert.equal(rumble.length,1);assert.equal(rumble[0][0],'dual-rumble');
assert.equal(rumble[0][1].duration,350);assert.equal(rumble[0][1].strongMagnitude,.65);
feedback.update(session,500);assert.equal(rumble.length,1); // one pulse, not repeated
assert.match(feedback.describe(500),/rumble supported/);
assert.match(feedback.describe(500),/self-test running/);
feedback.update(session,1601);assert.equal(rumble.at(-1)[1].strongMagnitude,0);
setImmediate(()=>{
 assert.match(feedback.describe(1601),/completed 1/);
 console.log('PASS: per-hand pulses, cap, cadence, expiry, hidden XR, reset, optional actuators, rumble fallback and one-shot self-test');
});
