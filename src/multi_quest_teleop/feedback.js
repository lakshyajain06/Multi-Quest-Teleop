/* Optional robot contact feedback for the shared Quest client: latest contact sample, brief haptics,
 * and a headset-local peripheral overlay independent of video reprojection. */
function createContactFeedback() {
  let sample = null, receivedAt = -Infinity, sequence = -1;
  let opacity = 0, previousFrame = null, activeRenderer = null;
  const pulses = new Map();
  const clamp = (value, maximum) => Number.isFinite(value) ? Math.max(0, Math.min(maximum, value)) : 0;

  function receive(value, now = performance.now()) {
    if (value?.version !== 1 || !Number.isSafeInteger(value.seq) || value.seq <= sequence) return;
    sequence = value.seq;
    receivedAt = now;
    sample = {left: clamp(value.haptics?.left, .65), right: clamp(value.haptics?.right, .65),
              collision: value.self_collision === true};
  }

  function pulse(actuator, intensity, duration) {
    try {
      const result = actuator?.pulse?.(intensity, duration);
      result?.catch?.(() => {});
    } catch {}
  }

  function reset(session) {
    for (const source of session?.inputSources || []) pulse(source.gamepad?.hapticActuators?.[0], 0, 1);
    pulses.clear();
    sample = null; receivedAt = -Infinity; sequence = -1;
    opacity = 0; previousFrame = null;
    activeRenderer?.dispose(); activeRenderer = null;
  }

  function update(session, now) {
    const fresh = now - receivedAt < 250 && session.visibilityState === 'visible';
    const target = fresh && sample?.collision ? .28 : 0;
    const dt = previousFrame === null ? 16 : Math.max(0, Math.min(100, now - previousFrame));
    opacity += (target - opacity) * (1 - Math.exp(-dt / 70));
    previousFrame = now;
    const present = new Set();
    for (const source of session.inputSources || []) {
      const hand = source.handedness;
      const actuator = source.gamepad?.hapticActuators?.[0];
      if (!actuator || !['left', 'right'].includes(hand)) continue;
      present.add(actuator);
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

  function renderer(gl, session) {
    const shader = (type, text) => {
      const value = gl.createShader(type); gl.shaderSource(value, text); gl.compileShader(value);
      if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(value));
      return value;
    };
    const vertex = shader(gl.VERTEX_SHADER,
      'attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.0)*0.5; gl_Position=vec4(p,0.,1.);}');
    const fragment = shader(gl.FRAGMENT_SHADER,
      'precision mediump float; varying vec2 uv; uniform float opacity; void main(){float edge=min(min(uv.x,1.-uv.x),min(uv.y,1.-uv.y)); float fade=1.-smoothstep(0.,.13,edge); gl_FragColor=vec4(.9,.025,.025,opacity*fade);}');
    const program = gl.createProgram(); gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
    gl.deleteShader(vertex); gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
    const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'p'), amount = gl.getUniformLocation(program, 'opacity');
    const result = {
      draw(views, layer, opacity) {
        if (!views || opacity < .001) return;
        gl.useProgram(program); gl.disable(gl.DEPTH_TEST);
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.enableVertexAttribArray(position);
        gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0); gl.uniform1f(amount, opacity);
        for (const view of views) {
          const port = layer.getViewport(view);
          gl.enable(gl.SCISSOR_TEST); gl.scissor(port.x, port.y, port.width, port.height);
          gl.viewport(port.x, port.y, port.width, port.height); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        }
        gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST);
      },
      dispose() { gl.deleteBuffer(buffer); gl.deleteProgram(program); }
    };
    session.addEventListener('end', () => { if (activeRenderer === result) {result.dispose(); activeRenderer = null;} }, {once:true});
    return result;
  }

  return {
    receive, reset, update,
    frame(session, now, gl, views, layer) {
      const alpha = update(session, now);
      if (alpha < .001) return;
      activeRenderer ||= renderer(gl, session);
      activeRenderer.draw(views, layer, alpha);
    }
  };
}
