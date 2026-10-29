import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {EXRLoader} from 'three/addons/loaders/EXRLoader.js';
import {STLLoader} from 'three/addons/loaders/STLLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import type {ArtifactRecord} from './contracts.generated';
import {artifactBlob,deliverySTLBlob,transferLabel,type ArtifactProgress} from './api';
import PreviewToolbar,{ViewerIcon,type PreviewAction} from './PreviewToolbar';
import {preparePreview,viewPose,modelStats,type StandardView} from './preview-geometry';
import './result-preview.css';

type Environment='studio'|'forest';
type Engine={scene:THREE.Scene;camera:THREE.PerspectiveCamera;controls:OrbitControls;model:THREE.Group;
  renderer:THREE.WebGLRenderer;key:THREE.DirectionalLight;ambient:THREE.HemisphereLight;grid:THREE.GridHelper;
  view:(view:StandardView)=>void;environment:(mode:Environment)=>Promise<boolean>};
const views:[StandardView,string][]=[['front','正视图'],['back','背视图'],['top','顶视图'],['bottom','底视图'],['left','左视图'],['right','右视图']];

export default function ResultPreview({run,artifact,frame,stlAvailable,dimensionsMm}:{
  run:string;artifact:ArtifactRecord;frame?:'y_up'|'z_up';stlAvailable:boolean;dimensionsMm?:number[]|null;
}){
  const host=useRef<HTMLDivElement>(null),viewport=useRef<HTMLDivElement>(null),engine=useRef<Engine|null>(null);
  const [format,setFormat]=useState<'glb'|'stl'>('glb'),[ready,setReady]=useState(false),[error,setError]=useState('');
  const [phase,setPhase]=useState('正在读取模型…'),[progress,setProgress]=useState<ArtifactProgress|null>(null),[attempt,setAttempt]=useState(0);
  const [rotate,setRotate]=useState(false),[wireframe,setWireframe]=useState(false),[background,setBackground]=useState('#dddddd');
  const [environment,setEnvironment]=useState<Environment>('studio'),[environmentNotice,setEnvironmentNotice]=useState('');
  const [lighting,setLighting]=useState(false),[fullscreen,setFullscreen]=useState(false);
  const [lights,setLights]=useState({key:1.9,ambient:1.6,exposure:1,grid:false});
  const [stats,setStats]=useState<ReturnType<typeof modelStats>&{fileBytes:number}|null>(null);
  const isSTL=format==='stl'&&stlAvailable;
  useEffect(()=>{const change=()=>setFullscreen(document.fullscreenElement===viewport.current);document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change);},[]);
  useEffect(()=>{
    const container=host.current!;const abort=new AbortController();let disposed=false,environmentRequest=0;
    let renderer:THREE.WebGLRenderer|undefined,controls:OrbitControls|undefined,observer:ResizeObserver|undefined;
    let environmentMap:THREE.WebGLRenderTarget|undefined,content:THREE.Object3D|undefined;
    const scene=new THREE.Scene();scene.background=new THREE.Color('#dddddd');
    const camera=new THREE.PerspectiveCamera(40,1,.01,100);
    engine.current=null;setReady(false);setError('');setStats(null);setProgress(null);setPhase('正在读取本任务模型…');
    setRotate(false);setWireframe(false);setBackground('#dddddd');setEnvironment('studio');setEnvironmentNotice('');setLighting(false);
    setLights({key:1.9,ambient:1.6,exposure:1,grid:false});
    async function load(){
      try{
        if(isSTL&&(!artifact.mesh_version||artifact.unit!=='mm'))throw Error('STL预览缺少同版本毫米几何依据');
        const options={signal:abort.signal,onProgress:(value:ArtifactProgress)=>{if(!disposed)setProgress(value);}};
        const blob=await (isSTL?deliverySTLBlob(run,artifact.mesh_version!,options):artifactBlob(run,artifact.artifact_id,options));
        const bytes=await blob.arrayBuffer();if(disposed)return;
        setProgress(null);setPhase('文件已读取，正在解析模型…');
        if(isSTL){
          const geometry=new STLLoader().parse(bytes);geometry.computeVertexNormals();
          content=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:'#c49c83',roughness:.6,metalness:0,side:THREE.DoubleSide}));
        }else{
          const manager=new THREE.LoadingManager();manager.setURLModifier(url=>{
            if(!url.startsWith('blob:')&&!url.startsWith('data:'))throw Error('拒绝读取模型中的外部资源');return url;
          });
          content=(await new GLTFLoader(manager).parseAsync(bytes,'')).scene;
        }
        if(disposed){disposeObject(content);return;}
        const fileStats=modelStats(content);
        // STL诊断色仅用于查看，文件本身没有材质。
        setStats({...fileStats,materials:isSTL?0:fileStats.materials,fileBytes:blob.size});
        const prepared=preparePreview(content,isSTL?'z_up':frame||'y_up');scene.add(prepared.root);
        const grid=new THREE.GridHelper(6,24,0x9ca3af,0xc8ccd0);grid.position.y=prepared.floorY-.002;grid.visible=false;scene.add(grid);
        const ambient=new THREE.HemisphereLight(0xffffff,0xb5bcc6,1.6),key=new THREE.DirectionalLight(0xffffff,1.9);key.position.set(3,5,4);scene.add(ambient,key);
        renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));
        renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
        container.replaceChildren(renderer.domElement);renderer.domElement.setAttribute('aria-label',isSTL?'STL模型画布':'GLB模型画布');
        controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.autoRotate=false;
        controls.autoRotateSpeed=1.3;controls.target.set(0,0,0);controls.minDistance=prepared.radius*.3;controls.maxDistance=prepared.radius*30;
        const view=(name:StandardView)=>{
          const pose=viewPose(name,prepared.radius,camera.fov,camera.aspect);camera.position.copy(pose.position);camera.up.copy(pose.up);
          camera.near=prepared.radius/1000;camera.far=prepared.radius*100;camera.updateProjectionMatrix();
          controls!.target.copy(pose.target);controls!.update();
        };
        const switchEnvironment=async(mode:Environment)=>{
          const request=++environmentRequest;setEnvironmentNotice(mode==='forest'?'正在读取森林HDR…':'');
          let next:THREE.WebGLRenderTarget|undefined;
          try{
            const generator=new THREE.PMREMGenerator(renderer!);
            try{
              if(mode==='studio'){
                const room=new RoomEnvironment();try{next=generator.fromScene(room,.04);}finally{room.dispose();}
              }else{
                const hdr=await new EXRLoader().loadAsync('/environment/forest.exr');
                try{if(disposed||request!==environmentRequest)return false;hdr.mapping=THREE.EquirectangularReflectionMapping;next=generator.fromEquirectangular(hdr);}finally{hdr.dispose();}
              }
            }finally{generator.dispose();}
            if(disposed||request!==environmentRequest){next?.dispose();return false;}
            scene.environment=next!.texture;environmentMap?.dispose();environmentMap=next;
            scene.environmentIntensity=mode==='studio'?.7:1;
            if(mode==='forest'){
              const lookup=new THREE.Matrix4().makeRotationY(-Math.PI/2).multiply(new THREE.Matrix4().makeRotationX(Math.PI/2));
              const r=new THREE.Euler().setFromRotationMatrix(lookup);scene.environmentRotation.set(-r.x,-r.y,-r.z);
            }else scene.environmentRotation.set(0,0,0);
            setEnvironmentNotice('');return true;
          }catch(exc){if(!disposed&&request===environmentRequest)setEnvironmentNotice('环境切换失败，保留当前照明：'+String(exc));return false;}
        };
        engine.current={scene,camera,controls,model:prepared.root,renderer,key,ambient,grid,view,environment:switchEnvironment};
        let initial=true;
        const resize=()=>{
          if(!renderer)return;const width=Math.max(1,container.clientWidth),height=Math.max(1,container.clientHeight);
          renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();
          if(initial){view('perspective');initial=false;}
        };
        observer=new ResizeObserver(resize);observer.observe(container);resize();await switchEnvironment('studio');
        if(disposed)return;
        renderer.setAnimationLoop(()=>{controls?.update();renderer?.render(scene,camera);});setReady(true);
      }catch(exc){if(!disposed){setProgress(null);setError(exc instanceof Error?exc.message:'模型预览失败');}}
    }
    void load();
    return()=>{disposed=true;environmentRequest++;abort.abort();engine.current=null;observer?.disconnect();controls?.dispose();renderer?.setAnimationLoop(null);environmentMap?.dispose();renderer?.dispose();disposeObject(scene);container.replaceChildren();};
  },[run,artifact.artifact_id,artifact.relative_path,artifact.mesh_version,artifact.unit,frame,isSTL,attempt]);

  function action(value:PreviewAction){
    const e=engine.current;if(!e)return;
    if(value==='in'||value==='out')e.camera.position.sub(e.controls.target).multiplyScalar(value==='in'?.8:1.25).add(e.controls.target);
    if(value==='rotate'){e.controls.autoRotate=!e.controls.autoRotate;setRotate(e.controls.autoRotate);}
    if(value==='wireframe'){
      const next=!wireframe;setWireframe(next);e.model.traverse(node=>{const m=node as THREE.Mesh;
        if(m.isMesh)for(const material of Array.isArray(m.material)?m.material:[m.material])if('wireframe' in material)(material as THREE.MeshStandardMaterial).wireframe=next;
      });
    }
    if(value==='reset'){e.model.rotation.set(0,0,0);e.controls.autoRotate=false;setRotate(false);e.view('perspective');e.grid.position.y=new THREE.Box3().setFromObject(e.model).min.y-.002;}
    if(value==='snapshot'){e.renderer.render(e.scene,e.camera);e.renderer.domElement.toBlob(blob=>{if(blob)save(blob,`preview-${run}-${isSTL?'stl':'glb'}.png`);});}
    if(value==='environment'){const next=environment==='studio'?'forest':'studio';void e.environment(next).then(ok=>{if(ok&&engine.current===e)setEnvironment(next);});}
    if(value==='lighting')setLighting(value=>!value);
    e.controls.update();
  }
  async function toggleFullscreen(){try{if(document.fullscreenElement===viewport.current)await document.exitFullscreen();else await viewport.current?.requestFullscreen();}catch{setEnvironmentNotice('当前浏览器不支持全屏，请使用窗口预览。');}}
  function exportInfo(){save(new Blob([JSON.stringify({run_id:run,artifact_id:artifact.artifact_id,mesh_version:artifact.mesh_version,
    preview_format:isSTL?'stl':'glb',file_statistics:stats,dimensions_mm:dimensionsMm??null,
    source_up_axis:isSTL?'z':frame==='z_up'?'z':'y',display_up_axis:'y',preview_only:true,print_certified:false},null,2)],{type:'application/json'}),`model-info-${run}-${isSTL?'stl':'glb'}.json`);}
  return <div className="result-preview">
    <div className="result-heading"><div className="result-formats" role="group" aria-label="结果预览格式">
      <button type="button" aria-pressed={!isSTL} onClick={()=>setFormat('glb')}>GLB彩色预览</button>
      <button type="button" aria-pressed={isSTL} disabled={!stlAvailable} onClick={()=>setFormat('stl')}>STL几何预览</button>
    </div><span>{isSTL?'不含纹理颜色':'保留本次UV/PBR材质'}</span></div>
    <div className="result-viewport" ref={viewport}>
      <div className="result-canvas" ref={host}/>
      <button className="result-fullscreen" type="button" aria-label={fullscreen?'退出全屏':'全屏展示'} title={fullscreen?'退出全屏':'全屏展示'} onClick={()=>void toggleFullscreen()}><ViewerIcon name="fullscreen"/></button>
      {(!ready||error)&&<div className="result-loading" role={error?'alert':'status'}><strong>{error|| (progress?transferLabel(progress):phase)}</strong>
        {!error&&progress&&<progress aria-label="结果模型读取进度" max={progress.total||undefined} value={progress.total?progress.loaded:undefined}/>}
        {error&&<button type="button" onClick={()=>setAttempt(value=>value+1)}>重新加载预览</button>}
      </div>}
      <PreviewToolbar disabled={!ready} rotate={rotate} wireframe={wireframe} background={background} onAction={action}
        onBackground={value=>{setBackground(value);if(engine.current)engine.current.scene.background=new THREE.Color(value);}}/>
      {lighting&&<div className="result-light-panel"><strong>光照与显示</strong>
        <label>主光强度<input type="range" aria-label="主光强度" min="0" max="4" step=".1" value={lights.key} onChange={event=>{const value=Number(event.target.value);setLights(old=>({...old,key:value}));if(engine.current)engine.current.key.intensity=value;}}/></label>
        <label>环境光强度<input type="range" aria-label="环境光强度" min="0" max="3" step=".1" value={lights.ambient} onChange={event=>{const value=Number(event.target.value);setLights(old=>({...old,ambient:value}));if(engine.current)engine.current.ambient.intensity=value;}}/></label>
        <label>曝光<input type="range" aria-label="预览曝光" min=".25" max="2" step=".05" value={lights.exposure} onChange={event=>{const value=Number(event.target.value);setLights(old=>({...old,exposure:value}));if(engine.current)engine.current.renderer.toneMappingExposure=value;}}/></label>
        <label className="result-grid"><input type="checkbox" checked={lights.grid} onChange={event=>{const value=event.target.checked;setLights(old=>({...old,grid:value}));if(engine.current)engine.current.grid.visible=value;}}/>显示底面网格</label>
        <div className="result-axis"><span>仅旋转显示方向</span>{(['x','y','z'] as const).map(axis=><button type="button" key={axis} onClick={()=>{const e=engine.current;if(e){e.model.rotateOnWorldAxis(new THREE.Vector3(axis==='x'?1:0,axis==='y'?1:0,axis==='z'?1:0),Math.PI/2);e.grid.position.y=new THREE.Box3().setFromObject(e.model).min.y-.002;}}}>{axis.toUpperCase()}轴90°</button>)}</div>
      </div>}
    </div>
    <div className="result-view-row"><span>视图控制</span><div>{views.map(([view,label])=><button type="button" key={view} disabled={!ready} onClick={()=>{const e=engine.current;if(e){e.controls.autoRotate=false;setRotate(false);e.view(view);}}}>{label}</button>)}</div></div>
    <p className="result-hint">拖动旋转 · 滚轮缩放 · 右键平移 · {environment==='studio'?'柔光棚拍环境':'官方森林HDR环境'}{isSTL?' · 已按Z朝上转换显示':''}<br/>显示调整不改文件；尺寸以毫米报告为准，预览不代表打印合格。</p>
    {environmentNotice&&<p role="status" className="result-environment-notice">{environmentNotice}</p>}
    {stats&&<div className="result-info"><div className="result-info-title"><strong>模型信息</strong><button type="button" onClick={exportInfo}>导出JSON</button></div>
      <dl><div><dt>文件顶点数</dt><dd>{stats.vertices.toLocaleString()}</dd></div><div><dt>三角面数</dt><dd>{stats.triangles.toLocaleString()}</dd></div><div><dt>材质数</dt><dd>{stats.materials}</dd></div><div><dt>文件大小</dt><dd>{(stats.fileBytes/1000000).toFixed(2)}MB</dd></div></dl>
      <p>{dimensionsMm?'交付尺寸：'+dimensionsMm.map(v=>v.toFixed(2)).join(' × ')+'mm':'原始文件无目标毫米尺度，不作尺寸测量。'}<br/>网格：{artifact.mesh_version}</p>
    </div>}
  </div>;
}

function save(blob:Blob,name:string){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function disposeObject(object:THREE.Object3D){
  const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>();
  object.traverse(node=>{const mesh=node as THREE.Mesh;if(!mesh.isMesh&&!(node as THREE.LineSegments).isLineSegments)return;
    if(mesh.geometry)geometries.add(mesh.geometry);for(const material of Array.isArray(mesh.material)?mesh.material:[mesh.material])if(material){materials.add(material);for(const value of Object.values(material))if(value instanceof THREE.Texture)textures.add(value);}
  });
  textures.forEach(value=>value.dispose());materials.forEach(value=>value.dispose());geometries.forEach(value=>value.dispose());
}
