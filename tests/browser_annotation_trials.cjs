// Production HUD checks without a headset. Video projection must remain separate.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'../src/multi_quest_teleop/feedback.js'),'utf8'));
const labels=[],rects=[],viewports=[];
let draws=0,uploads=0;
global.document={createElement:()=>({getContext:()=>({clearRect(){},fillRect(){},
  fillText(text){labels.push(text);}})})};
const gl=new Proxy({
  getShaderParameter:()=>true,getProgramParameter:()=>true,getAttribLocation:()=>0,
  getUniformLocation:(_,name)=>name,
  uniform4f:(_, ...values)=>rects.push(values),
  viewport:(...values)=>viewports.push(values),
  drawArrays:()=>draws++,texImage2D:()=>uploads++,
  uniformMatrix4fv(){throw Error('HUD must not change the video projection');}
},{get(target,name){return name in target ? target[name] : (/^[A-Z_0-9]+$/.test(name) ? 1 : ()=>({}));}});
const hud=createAnnotationHUD(gl),views=[{eye:'left'},{eye:'right'}];
const layer={getViewport:view=>({x:view.eye==='left' ? 0 : 512,y:0,width:512,height:512})};
const feedback=(seq,sequence,task,cycles=0)=>({version:1,seq,
  annotation:{version:1,robot:'ultra',task,completed_cycles:cycles,sequence}});
hud.draw(views,layer,0);assert.equal(draws,0);
hud.receive(feedback(0,0,'Setting up'),0);hud.draw(views,layer,1);
assert.equal(draws,2);assert.equal(uploads,1);
assert.deepEqual(viewports,[[0,0,512,512],[512,0,512,512]]);
assert.deepEqual(rects[0],rects[1]);
assert(Math.abs((rects[0][0]+rects[0][2])/2-.5)<1e-6 && rects[0][3]<.5); // centered below the middle in both eyes
assert(rects[0][2]-rects[0][0]<.35);
assert.deepEqual(labels,['Ultra: Setting up','Completed cycles: 0']);
hud.receive(feedback(1,1,'Pick up the cube'),10);assert.equal(uploads,2);
hud.receive(feedback(1,2,'Incorrect repeated ACK',10),20);assert.equal(uploads,2);
hud.receive(feedback(2,0,'Incorrect old video metadata',10),30);assert.equal(uploads,2);
hud.receive(feedback(3,2,'Pick up the cube',1),40);assert.equal(uploads,3);
assert.equal(labels.at(-1),'Completed cycles: 1');
hud.draw(views,layer,1600);assert.equal(draws,2); // stopped simulation expires
hud.receive(feedback(4,2,'Pick up the cube',1),1700);assert.equal(uploads,3);
hud.draw(views,layer,1701);assert.equal(draws,4); // live unchanged states renew freshness
hud.receive({version:1,seq:5},1800);hud.draw(views,layer,1801);assert.equal(draws,4);
hud.dispose();hud.draw(views,layer,1802);assert.equal(draws,4);
console.log('PASS: per-operator task/cycle HUD, identical eye placement, stale-data expiry, reordered metadata, and separate video projection');
