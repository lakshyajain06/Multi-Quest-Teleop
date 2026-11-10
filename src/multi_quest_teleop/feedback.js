/* Optional robot contact feedback for the shared Quest client: latest contact sample, brief haptics,
 * and a headset-local video tint independent of video reprojection. */
function createContactFeedback() {
  let sample = null, receivedAt = -Infinity, sequence = -1;
  let opacity = 0, previousFrame = null;
  const red = [.95,.025,.025], orange = [1.,.45,.015];
  let color = red;
  let testUntil = -Infinity, packets = 0, requested = 0, completed = 0, lastError = '';
  let hands = {}, forces = {left:0,right:0};
  const pulses = new Map();
  const tested = new Set();
  const clamp = (value, maximum) => Number.isFinite(value) ? Math.max(0, Math.min(maximum, value)) : 0;

  function receive(value, now = performance.now()) {
    if (value?.version !== 1 || !Number.isSafeInteger(value.seq) || value.seq <= sequence) return;
    sequence = value.seq;
    receivedAt = now;
    packets++;
    forces = {left:clamp(value.arm_force_n?.left,1e6),right:clamp(value.arm_force_n?.right,1e6)};
    const blocked = value.command_blocked === true || value.collision_blocked === true;
    const reasons = Object.entries(value.blocked_commands || {}).slice(0,8);
    sample = {left: clamp(value.haptics?.left, .65), right: clamp(value.haptics?.right, .65),
              collision: value.self_collision === true,
              collisionBlocked: value.collision_blocked === true || (blocked && reasons.some(([,reason])=>['self_collision','collision'].includes(reason))),
              blocked,
              reasons: reasons.map(([name,reason])=>`${name}: ${reason}`).join(', ')};
  }

  function pulse(actuator, intensity, duration) {
    try {
      const result = typeof actuator?.pulse === 'function' ? actuator.pulse(intensity, duration)
        : actuator?.playEffect?.('dual-rumble',{duration,startDelay:0,strongMagnitude:intensity,weakMagnitude:intensity});
      if (intensity > 0) requested++;
      result?.then?.(value => {if (value === true || value === 'complete') completed++;})
        ?.catch?.(error => {lastError=String(error?.name || error).slice(0,80);});
    } catch (error) {lastError=String(error?.name || error).slice(0,80);}
  }

  function actuatorFor(source) {
    const pad=source.gamepad;
    return [...(pad?.hapticActuators || []),pad?.vibrationActuator]
      .find(value=>typeof value?.pulse==='function' || typeof value?.playEffect==='function');
  }

  function describe(now=performance.now()) {
    const signal=packets ? `Contact signals: ${now-receivedAt<250 ? 'live' : 'stale'} (${packets}) · L ${forces.left.toFixed(1)} N / R ${forces.right.toFixed(1)} N · self-contact ${sample?.collision ? 'yes' : 'no'}` : 'Contact signals: waiting';
    return `${signal}${sample?.blocked ? '\nCommands blocked: '+(sample.reasons || 'rejected target') : ''}\nHaptics: L ${hands.left || 'not detected'} / R ${hands.right || 'not detected'} · requests ${requested}, completed ${completed}${lastError ? ' · '+lastError : ''}${now<testUntil ? '\nFeedback self-test running' : ''}`;
  }

  function reset(session) {
    for (const source of session?.inputSources || []) pulse(actuatorFor(source), 0, 1);
    pulses.clear();
    tested.clear();testUntil=-Infinity;packets=0;requested=0;completed=0;lastError='';hands={};forces={left:0,right:0};
    sample = null; receivedAt = -Infinity; sequence = -1;
    opacity = 0; previousFrame = null;
    color = red;
  }

  function update(session, now) {
    const fresh = now - receivedAt < 250 && session.visibilityState === 'visible';
    const testing = now < testUntil && session.visibilityState === 'visible';
    const collision = fresh && (sample?.collision || sample?.collisionBlocked);
    const blocked = fresh && sample?.blocked;
    const target = testing ? .35 : (collision || blocked ? .22 : 0);
    if (testing || collision) color = red;
    else if (blocked) color = orange;
    const dt = previousFrame === null ? 16 : Math.max(0, Math.min(100, now - previousFrame));
    opacity += (target - opacity) * (1 - Math.exp(-dt / 70));
    previousFrame = now;
    const present = new Set();
    for (const source of session.inputSources || []) {
      const hand = source.handedness;
      if (!['left', 'right'].includes(hand)) continue;
      const actuator = actuatorFor(source);
      hands[hand]=actuator ? (typeof actuator.pulse==='function' ? 'pulse supported' : 'rumble supported') : 'unavailable';
      if (!actuator) continue;
      present.add(actuator);
      if (testing) {
        if (!tested.has(actuator)) {
          pulse(actuator,.65,350);tested.add(actuator);pulses.set(actuator,{at:now,intensity:.65});
        }
        continue;
      }
      const intensity = fresh ? sample?.[hand] || 0 : 0;
      const previous = pulses.get(actuator);
      if (intensity > 0 && (!previous || previous.intensity === 0 || now - previous.at >= 75)) {
        pulse(actuator, intensity, 80);
        pulses.set(actuator, {at: now, intensity});
      } else if (intensity === 0 && previous?.intensity > 0) {
        pulse(actuator, 0, 1);
        pulses.set(actuator, {at: now, intensity: 0});
      }
    }
    for (const actuator of pulses.keys()) if (!present.has(actuator)) {
      pulse(actuator, 0, 1); pulses.delete(actuator);
    }
    return opacity;
  }

  return {
    receive, reset, update, describe,
    get color() {return color;},
    startTest(now=performance.now()) {testUntil=now+1200;tested.clear();},

  };
}

/* A headset-local task panel, composited after video reprojection in each eye.
 * Its pixels never enter the streamed camera images or recorded datasets. */
function createAnnotationHUD(gl) {
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=128;
  const context=canvas.getContext('2d');
  let sample=null,receivedAt=-Infinity,feedbackSequence=-1,annotationSequence=-1,key='';
  const shader=(type,code)=>{
    const value=gl.createShader(type);gl.shaderSource(value,code);gl.compileShader(value);
    if(!gl.getShaderParameter(value,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(value));
    return value;
  };
  const vertex=shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; uniform vec4 rect; void main(){uv=(p+1.)*.5;gl_Position=vec4(mix(rect.xy,rect.zw,uv)*2.-1.,0.,1.);}');
  const fragment=shader(gl.FRAGMENT_SHADER,'precision mediump float; varying vec2 uv; uniform sampler2D image; void main(){gl_FragColor=texture2D(image,uv);}');
  const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
  gl.deleteShader(vertex);gl.deleteShader(fragment);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
  const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  return {
    receive(feedback,now=performance.now()) {
      if(feedback?.version!==1 || !Number.isSafeInteger(feedback.seq) || feedback.seq<=feedbackSequence)return;
      const value=feedback.annotation;
      if(!value){sample=null;feedbackSequence=feedback.seq;return;}
      if(value.version!==1 || !['ultra','yor'].includes(value.robot) || typeof value.task!=='string'
          || !value.task.length || value.task.length>80 || !Number.isSafeInteger(value.completed_cycles)
          || value.completed_cycles<0 || !Number.isSafeInteger(value.sequence)
          || value.sequence<0 || value.sequence<annotationSequence)return;
      feedbackSequence=feedback.seq;annotationSequence=value.sequence;receivedAt=now;
      sample={robot:value.robot,task:value.task,cycles:value.completed_cycles};
      const nextKey=JSON.stringify(sample);
      if(nextKey===key)return;
      key=nextKey;
      context.clearRect(0,0,512,128);context.fillStyle='rgba(0,0,0,.75)';context.fillRect(0,0,512,128);
      context.textAlign='right';context.textBaseline='middle';context.fillStyle='white';
      context.font='bold 34px system-ui';
      context.fillText(`${sample.robot==='ultra' ? 'Ultra' : 'YOR'}: ${sample.task}`,496,38,480);
      context.font='30px system-ui';context.fillText(`Completed cycles: ${sample.cycles}`,496,91,480);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,canvas);
    },
    draw(views,layer,now=performance.now()) {
      if(!sample || !views || now-receivedAt>1500)return;
      gl.useProgram(program);gl.disable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
      gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      const position=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);
      gl.uniform1i(gl.getUniformLocation(program,'image'),0);
      for(const view of views){
        const viewport=layer.getViewport(view),width=.43,height=width*viewport.width/viewport.height/4;
        gl.enable(gl.SCISSOR_TEST);gl.scissor(viewport.x,viewport.y,viewport.width,viewport.height);
        gl.viewport(viewport.x,viewport.y,viewport.width,viewport.height);
        gl.uniform4f(gl.getUniformLocation(program,'rect'),.78-width,.74-height,.78,.74);
        gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
      }
      gl.disable(gl.SCISSOR_TEST);gl.disable(gl.BLEND);
    },
    dispose(){sample=null;gl.deleteTexture(texture);gl.deleteBuffer(buffer);gl.deleteProgram(program);}
  };
}
