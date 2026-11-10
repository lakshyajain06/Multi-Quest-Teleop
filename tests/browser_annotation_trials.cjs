// Exercise the production HUD's shared 3D panel with asymmetric XR eye projections.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'../src/multi_quest_teleop/feedback.js'),'utf8'));
const labels=[],draws=[],uniforms={};let uploads=0,viewport;
global.document={createElement:()=>({getContext:()=>({clearRect(){},fillRect(){},fillText(text){labels.push(text);}})})};
const gl=new Proxy({
  getShaderParameter:()=>true,getProgramParameter:()=>true,getAttribLocation:()=>0,
  getUniformLocation:(_,name)=>name,
  uniform4f:(name,...values)=>uniforms[name]=values,
  uniformMatrix4fv(name,transpose,matrix){assert.equal(transpose,false);uniforms[name]=Array.from(matrix);},
  viewport:(...values)=>viewport=values,
  drawArrays:()=>draws.push({...uniforms,viewport}),texImage2D:()=>uploads++
},{get(target,name){return name in target ? target[name] : (/^[A-Z_0-9]+$/.test(name) ? 1 : ()=>({}));}});
const identity=()=>[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const transform=(m,p)=>Array.from({length:4},(_,r)=>p.reduce((sum,value,c)=>sum+m[c*4+r]*value,0));
const multiply=(a,b)=>Array.from({length:16},(_,i)=>{const r=i%4,c=Math.floor(i/4);let value=0;for(let k=0;k<4;k++)value+=a[k*4+r]*b[c*4+k];return value;});
function inverseRigid(m){
  const result=identity();for(let r=0;r<3;r++)for(let c=0;c<3;c++)result[c*4+r]=m[r*4+c];
  for(let r=0;r<3;r++)result[12+r]=-(result[r]*m[12]+result[4+r]*m[13]+result[8+r]*m[14]);
  return result;
}
function pose(yaw=0,position=[0,1.6,0]){
  const c=Math.cos(yaw),s=Math.sin(yaw),head=[c,0,-s,0,0,1,0,0,s,0,c,0,...position,1];
  return {transform:{matrix:head},views:['left','right'].map((eye,i)=>{
    const offset=identity();offset[12]=i ? .032 : -.032;
    return {eye,projectionMatrix:[1.1,0,0,0,0,1.2,0,0,i ? .13 : -.13,-.06,-1.002,-1,0,0,-.2002,0],
      transform:{inverse:{matrix:inverseRigid(multiply(head,offset))}}};
  })};
}
const layer={getViewport:view=>({x:view.eye==='left' ? 0 : 512,y:0,width:512,height:512})};
const feedback=(seq,sequence,task,cycles=0)=>({version:1,seq,
  annotation:{version:1,robot:'ultra',task,completed_cycles:cycles,sequence}});
function verifyStereo(currentPose,pair){
  const projected=[];
  for(let i=0;i<2;i++){
    const draw=pair[i],[width,height,centerY,distance]=draw.panel;
    assert(distance>=1 && distance<=3 && width/distance<.7 && height<width && centerY<0);
    assert.deepEqual(draw.projection,currentPose.views[i].projectionMatrix);
    assert.deepEqual(draw.eyeFromWorld,currentPose.views[i].transform.inverse.matrix);
    assert.deepEqual(draw.worldFromHead,currentPose.transform.matrix);
    const center=[0,centerY,-distance,1];
    const clip=transform(draw.projection,transform(draw.eyeFromWorld,transform(draw.worldFromHead,center)));
    const ndc=[clip[0]/clip[3],clip[1]/clip[3]];projected.push(ndc);
    // Unproject each eye's panel center independently: the rays must meet on one head-relative plane.
    const eyeFromClipRay=[(ndc[0]+draw.projection[8])/draw.projection[0],(ndc[1]+draw.projection[9])/draw.projection[5],-1,0];
    const headFromEye=multiply(inverseRigid(draw.worldFromHead),inverseRigid(draw.eyeFromWorld));
    const origin=transform(headFromEye,[0,0,0,1]),direction=transform(headFromEye,eyeFromClipRay);
    const t=(-distance-origin[2])/direction[2],hit=origin.slice(0,3).map((value,j)=>value+t*direction[j]);
    for(let j=0;j<3;j++)assert(Math.abs(hit[j]-center[j])<1e-6);
  }
  assert.notDeepEqual(projected[0],projected[1]); // Each eye gets its correct perspective, rather than duplicated viewport positions.
}
const hud=createAnnotationHUD(gl),initial=pose(),original=JSON.stringify(initial);
hud.draw(initial,layer,0);assert.equal(draws.length,0);
hud.receive(feedback(0,0,'Setting up'),0);hud.draw(initial,layer,1);
assert.equal(draws.length,2);assert.equal(uploads,1);
assert.deepEqual(draws.map(draw=>draw.viewport),[[0,0,512,512],[512,0,512,512]]);
verifyStereo(initial,draws.slice(-2));assert.equal(JSON.stringify(initial),original);
assert.deepEqual(labels,['Ultra: Setting up','Completed cycles: 0']);
const moved=pose(Math.PI/3,[1.2,1.8,-.7]),movedOriginal=JSON.stringify(moved);
hud.draw(moved,layer,2);verifyStereo(moved,draws.slice(-2));assert.equal(JSON.stringify(moved),movedOriginal);
const count=draws.length;hud.draw(null,layer,3);assert.equal(draws.length,count);
hud.receive(feedback(1,1,'Pick up the cube'),10);assert.equal(uploads,2);
hud.receive(feedback(1,2,'Incorrect repeated ACK',10),20);assert.equal(uploads,2);
hud.receive(feedback(2,0,'Incorrect old video metadata',10),30);assert.equal(uploads,2);
hud.receive(feedback(3,2,'Pick up the cube',1),40);assert.equal(uploads,3);
assert.equal(labels.at(-1),'Completed cycles: 1');
hud.draw(initial,layer,1600);assert.equal(draws.length,count);
hud.receive(feedback(4,2,'Pick up the cube',1),1700);assert.equal(uploads,3);
hud.draw(initial,layer,1701);assert.equal(draws.length,count+2);
hud.receive({version:1,seq:5},1800);hud.draw(initial,layer,1801);assert.equal(draws.length,count+2);
hud.dispose();hud.draw(initial,layer,1802);assert.equal(draws.length,count+2);
console.log('PASS: one stereo task panel with convergent eye rays, asymmetric projections, head motion, immutable XR matrices, and annotation freshness');
