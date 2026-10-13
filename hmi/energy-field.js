// Local WebGL 1 renderer: three small draw calls, no textures or remote dependencies.
// The SVG owns readable geometry. GPU particles follow those exact cubic paths.
const QUAD_VERTEX = `attribute vec2 a_position; void main(){gl_Position=vec4(a_position,0.,1.);}`;
const FIELD_FRAGMENT = `
precision mediump float;
uniform vec2 u_resolution;
uniform float u_time, u_idle, u_failure;
void main(){
  vec2 uv=gl_FragCoord.xy/u_resolution;
  vec2 p=(uv-.5)*vec2(u_resolution.x/u_resolution.y,1.);
  vec3 paper=vec3(1.,.976,.89), blue=vec3(.169,.361,.902), violet=vec3(.424,.247,.831);
  vec3 col=mix(paper,vec3(1.,.90,.86),u_failure*.45);
  vec2 cell=abs(fract(gl_FragCoord.xy/26.)-.5);
  float grid=1.-smoothstep(.005,.025,min(cell.x,cell.y));
  col=mix(col,vec3(.08),grid*.05);
  float wave=p.y+.20+.045*sin(p.x*10.-u_time*.6283185);
  float line=exp(-abs(wave)*180.);
  float echo=exp(-abs(wave+.028)*140.);
  col=mix(col,violet,line*u_idle*.25);
  col=mix(col,blue,echo*u_idle*.08);
  float pulse=exp(-pow((p.x-mod(u_time*.14+1.5,3.)+1.5)*13.,2.));
  col=mix(col,blue,pulse*line*u_idle*.6);
  gl_FragColor=vec4(col,1.);
}`;
const PARTICLE_VERTEX = `
precision mediump float;
attribute vec2 a_start,a_c1,a_c2,a_end;
attribute float a_phase,a_live,a_seed;
uniform vec2 u_css;
uniform float u_time,u_scale,u_failure,u_fall;
varying float v_alpha;
vec2 bezier(float t){float q=1.-t;return q*q*q*a_start+3.*q*q*t*a_c1+3.*q*t*t*a_c2+t*t*t*a_end;}
void main(){
  float t=fract(u_time*.19+a_phase);
  vec2 p=bezier(t);
  float fall=min(2.5,u_fall);
  p+=u_failure*vec2(sin(a_seed*6.28)*fall*95.,fall*fall*(80.+a_seed*60.));
  gl_Position=vec4(p.x/u_css.x*2.-1.,1.-p.y/u_css.y*2.,0.,1.);
  gl_PointSize=(3.+4.*pow(fract(a_phase*3.7),3.))*u_scale;
  v_alpha=a_live*(.20+.8*pow(1.-fract(t*3.),2.))*(1.-u_failure*min(1.,u_fall/2.5));
}`;
const PARTICLE_FRAGMENT = `
precision mediump float;
uniform float u_failure;
varying float v_alpha;
void main(){vec2 p=gl_PointCoord-.5;float a=exp(-dot(p,p)*14.);gl_FragColor=vec4(mix(vec3(.169,.361,.902),vec3(.73,.14,.24),u_failure),a*v_alpha);}
`;
const NODE_VERTEX = `
precision mediump float;
attribute vec2 a_center;
attribute float a_state,a_stamp,a_seed;
uniform vec2 u_css;
uniform float u_scale,u_time,u_failure,u_fall,u_point_limit;
varying float v_state,v_age,v_opacity;
void main(){
  vec2 p=a_center;
  p.y+=u_failure*min(2.,u_fall)*16.;
  gl_Position=vec4(p.x/u_css.x*2.-1.,1.-p.y/u_css.y*2.,0.,1.);
  gl_PointSize=min(u_point_limit,240.*u_scale);
  v_state=a_state;v_age=a_stamp;
  v_opacity=1.-u_failure*.65;
}`;
const NODE_FRAGMENT = `
precision mediump float;
varying float v_state,v_age,v_opacity;
uniform float u_failure,u_time;
void main(){
  float r=length(gl_PointCoord-.5)*2.;
  vec3 color=mix(vec3(.424,.247,.831),vec3(.169,.361,.902),step(1.5,v_state));
  color=mix(color,vec3(.95,.16,.32),u_failure);
  float aura=exp(-r*r*4.)*.16;
  float ring=exp(-pow((r-min(.95,v_age*.75+.12))/.035,2.))*exp(-v_age*1.5);
  float rim=exp(-abs(r-.72)*45.)*.08;
  float alpha=(aura+ring*.6+rim)*step(.5,v_state)*v_opacity;
  gl_FragColor=vec4(color,alpha);
}`;

export class EnergyField {
  constructor(canvas) {
    this.canvas=canvas; this.time=0; this.last=0; this.lastPaint=0; this.fallAt=0;
    this.model=null; this.svg=null; this.key=''; this.idle=1; this.failure=0;
    this.paused=false; this.reduced=false; this.dirty=true; this.stamps=new Map();
    this.programs=[]; this.buffers=[]; this.quality=1;
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.lost=true;document.body.classList.remove('webgl-on');canvas.dataset.renderer='fallback';});
    canvas.addEventListener('webglcontextrestored',()=>{this.lost=false;this.initialize();this.resize();this.geometry();});
    this.initialize();
    this.resizeObserver=new ResizeObserver(()=>{this.resize();this.geometry();});
    this.resizeObserver.observe(document.documentElement);
    window.addEventListener('resize',()=>{this.resize();this.geometry();});
    document.addEventListener('visibilitychange',()=>{this.last=0;this.dirty=true;});
    this.resize(); this.frame=this.frame.bind(this); requestAnimationFrame(this.frame);
  }
  program(vertex,fragment) {
    const gl=this.gl, p=gl.createProgram();
    for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]) {
      const sh=gl.createShader(type);gl.shaderSource(sh,source);gl.compileShader(sh);gl.attachShader(p,sh);gl.deleteShader(sh);
    }
    gl.bindAttribLocation(p,0,'a_position');gl.linkProgram(p);
    if(!gl.getProgramParameter(p,gl.LINK_STATUS)){const message=gl.getProgramInfoLog(p);gl.deleteProgram(p);throw Error(message);}
    this.programs.push(p);return p;
  }
  initialize() {
    this.programs=[];this.buffers=[];
    if(new URLSearchParams(location.search).get('effects')==='off'){this.canvas.dataset.renderer='fallback';return;}
    try {
      this.gl=this.canvas.getContext('webgl',{alpha:false,depth:false,stencil:false,antialias:false,powerPreference:'low-power'});
      if(!this.gl) throw Error('WebGL unavailable');
      const gl=this.gl;
      this.field=this.program(QUAD_VERTEX,FIELD_FRAGMENT);
      this.particles=this.program(PARTICLE_VERTEX,PARTICLE_FRAGMENT);
      this.nodes=this.program(NODE_VERTEX,NODE_FRAGMENT);
      this.locations=new Map();
      this.attributes=new Map();
      for(const p of this.programs) {
        const locations={};
        for(const name of ['u_resolution','u_css','u_time','u_idle','u_failure','u_fall','u_scale','u_point_limit']) locations[name]=gl.getUniformLocation(p,name);
        this.locations.set(p,locations);
        const attributes={};
        for(const name of ['a_position','a_start','a_c1','a_c2','a_end','a_phase','a_live','a_seed','a_center','a_state','a_stamp']) attributes[name]=gl.getAttribLocation(p,name);
        this.attributes.set(p,attributes);
      }
      this.quad=gl.createBuffer();this.particleBuffer=gl.createBuffer();this.nodeBuffer=gl.createBuffer();
      this.buffers=[this.quad,this.particleBuffer,this.nodeBuffer];
      gl.bindBuffer(gl.ARRAY_BUFFER,this.quad);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
      this.pointLimit=gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)[1];
      this.maxAttributes=gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
      gl.disable(gl.DEPTH_TEST);
      this.canvas.dataset.renderer='webgl';document.body.classList.add('webgl-on');
    } catch(error) {
      if(this.gl){for(const p of this.programs)this.gl.deleteProgram(p);for(const b of this.buffers)this.gl.deleteBuffer(b);}
      this.gl=null;this.canvas.dataset.renderer='fallback';document.body.classList.remove('webgl-on');
      console.info('Energy field: SVG fallback.',error.message);
    }
  }
  resize() {
    this.width=innerWidth;this.height=innerHeight;
    this.scale=Math.min(1,Math.sqrt(700000/(this.width*this.height)))*this.quality;
    this.canvas.width=Math.max(1,Math.round(this.width*this.scale));this.canvas.height=Math.max(1,Math.round(this.height*this.scale));
    this.dirty=true;
  }
  setMotion({paused=false,reduced=false}={}){if(this.paused!==paused||this.reduced!==reduced)this.dirty=true;this.paused=paused;this.reduced=reduced;}
  attach(svg,model,key,idle=false) {
    const signature=`${key}/${model?.nodes.map(n=>n.node_id+n.state).join(',')}/${model?.status}/${idle}`;
    if(this.key===signature&&this.svg===svg)return;
    if(model?.status==='collapsed'&&!this.failure)this.fallAt=this.time;
    this.failure=model?.status==='collapsed'?1:0;this.idle=idle?1:0;
    if(this.roundKey!==key){this.stamps.clear();this.roundKey=key;}
    for(const n of model?.nodes||[]) {
      const previous=this.stamps.get(n.node_id);
      if(!previous||previous.state!==n.state)this.stamps.set(n.node_id,{state:n.state,time:this.time});
    }
    if(this.svg!==svg) {
      if(this.svg?.parentElement)this.resizeObserver.unobserve(this.svg.parentElement);
      if(svg?.parentElement)this.resizeObserver.observe(svg.parentElement);
    }
    this.svg=svg;this.model=model;this.key=signature;this.geometry();
    requestAnimationFrame(()=>this.geometry());
  }
  geometry() {
    this.particleCount=0;this.nodeCount=0;this.dirty=true;
    if(!this.gl||this.lost||!this.svg?.isConnected||!this.model)return;
    const gl=this.gl,m=this.svg.getScreenCTM();if(!m)return;
    const point=(x,y)=>[m.a*x+m.c*y+m.e,m.b*x+m.d*y+m.f];
    const particles=[],nodes=[];this.nodeBirths=[];
    for(const edge of this.model.edges) {
      const path=this.svg.querySelector(`[data-edge="${edge.id}"] .edge-base`);
      if(!path||['observe','control','preparation'].includes(edge.kind))continue;
      const values=path.getAttribute('d').match(/-?\d+(?:\.\d+)?/g)?.map(Number);
      if(values?.length!==8)continue;
      const control=[];for(let i=0;i<8;i+=2)control.push(...point(values[i],values[i+1]));
      for(let i=0;i<18;i++)particles.push(...control,i/18,edge.state==='live'?1:0,(i*0.618)%1);
    }
    for(const n of this.model.nodes) {
      this.nodeBirths.push(this.stamps.get(n.node_id)?.time||0);
      nodes.push(...point(n.x+84,n.y+55),n.state==='live'?2:n.state==='ready'?1:0,0,n.x/1280);
    }
    this.particleCount=particles.length/11;this.nodeCount=nodes.length/5;
    gl.bindBuffer(gl.ARRAY_BUFFER,this.particleBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(particles),gl.DYNAMIC_DRAW);
    this.nodeData=new Float32Array(nodes);
    gl.bindBuffer(gl.ARRAY_BUFFER,this.nodeBuffer);gl.bufferData(gl.ARRAY_BUFFER,this.nodeData,gl.DYNAMIC_DRAW);
  }
  use(p,buffer,layout,stride) {
    const gl=this.gl;gl.useProgram(p);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    for(let i=0;i<this.maxAttributes;i++)gl.disableVertexAttribArray(i);
    let offset=0;
    for(const [name,size] of layout) {const loc=this.attributes.get(p)[name];if(loc>=0){gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,size,gl.FLOAT,false,stride*4,offset*4);}offset+=size;}
    const u=this.locations.get(p);
    gl.uniform2f(u.u_resolution,this.canvas.width,this.canvas.height);gl.uniform2f(u.u_css,this.width,this.height);
    // Bounded shader time avoids mediump precision loss during long kiosk runs.
    gl.uniform1f(u.u_time,this.time%100);gl.uniform1f(u.u_idle,this.idle);gl.uniform1f(u.u_failure,this.failure);
    gl.uniform1f(u.u_fall,this.reduced?3:Math.max(0,this.time-this.fallAt));gl.uniform1f(u.u_scale,this.scale);gl.uniform1f(u.u_point_limit,this.pointLimit);
  }
  frame(now) {
    requestAnimationFrame(this.frame);
    const delta=this.last?Math.min(.1,(now-this.last)/1000):0;this.last=now;
    if(document.hidden||!this.gl||this.lost)return;
    if(!this.paused&&!this.reduced)this.time+=delta;
    if((this.paused||this.reduced)&&!this.dirty)return;
    if(now-this.lastPaint<1000/30)return;
    this.lastPaint=now;this.dirty=false;
    const gl=this.gl,begin=performance.now();
    gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.disable(gl.BLEND);
    this.use(this.field,this.quad,[['a_position',2]],2);gl.drawArrays(gl.TRIANGLES,0,6);
    gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
    if(this.particleCount){this.use(this.particles,this.particleBuffer,[['a_start',2],['a_c1',2],['a_c2',2],['a_end',2],['a_phase',1],['a_live',1],['a_seed',1]],11);gl.drawArrays(gl.POINTS,0,this.particleCount);}
    if(this.nodeCount){
      for(let i=0;i<this.nodeCount;i++)this.nodeData[i*5+3]=this.reduced?8:Math.min(8,this.time-this.nodeBirths[i]);
      gl.bindBuffer(gl.ARRAY_BUFFER,this.nodeBuffer);gl.bufferSubData(gl.ARRAY_BUFFER,0,this.nodeData);
      this.use(this.nodes,this.nodeBuffer,[['a_center',2],['a_state',1],['a_stamp',1],['a_seed',1]],5);gl.drawArrays(gl.POINTS,0,this.nodeCount);
    }
    if(performance.now()-begin>22&&this.quality>.65){this.quality-=.1;this.resize();}
  }
}
