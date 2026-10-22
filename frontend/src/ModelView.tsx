import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {PLYLoader} from 'three/addons/loaders/PLYLoader.js';
import {STLLoader} from 'three/addons/loaders/STLLoader.js';
import {EXRLoader} from 'three/addons/loaders/EXRLoader.js';
import type {ArtifactRecord} from './contracts.generated';
import {artifactBlob,transferLabel,type ArtifactProgress} from './api';

export default function ModelView({run,artifact,frame}:{run:string;artifact:ArtifactRecord;frame?:'z_up'|'y_up'}) {
  const host=useRef<HTMLDivElement>(null);const [error,setError]=useState('');const [ready,setReady]=useState(false);
  const [attempt,setAttempt]=useState(0);const [progress,setProgress]=useState<ArtifactProgress|null>(null);
  const [phase,setPhase]=useState('正在读取本任务模型…');
  useEffect(()=>{
    const container=host.current!;let disposed=false;let renderer:THREE.WebGLRenderer|undefined;
    const controller=new AbortController();let stage='model';
    let object:THREE.Object3D|undefined;let controls:OrbitControls|undefined;let observer:ResizeObserver|undefined;
    let environment:THREE.WebGLRenderTarget|undefined;
    setReady(false);setError('');setProgress(null);setPhase('正在读取本任务模型…');
    const scene=new THREE.Scene();scene.background=new THREE.Color('#eeeee9');
    const camera=new THREE.PerspectiveCamera(40,1,.01,100);
    async function load() {
      try {
        const data=await (await artifactBlob(run,artifact.artifact_id,{signal:controller.signal,
          onProgress:value=>{if(!disposed)setProgress(value);}})).arrayBuffer();
        if(disposed)return;
        stage='parse';setProgress(null);setPhase('文件已读取，正在解析模型…');
        const extension=artifact.relative_path.split('.').at(-1)?.toLowerCase();
        if(extension==='glb') {
          const manager=new THREE.LoadingManager();
          manager.setURLModifier(url=>{if(!url.startsWith('blob:')&&!url.startsWith('data:'))throw Error('拒绝加载模型中的外部资源');return url;});
          object=(await new GLTFLoader(manager).parseAsync(data,'')).scene;
        } else {
          const geometry=extension==='stl'?new STLLoader().parse(data):new PLYLoader().parse(data);
          geometry.computeVertexNormals();
          const hasColor=geometry.hasAttribute('color');
          object=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:hasColor?'#ffffff':'#849ca2',vertexColors:hasColor,roughness:.85,side:THREE.DoubleSide}));
        }
        // 显式坐标来自服务端；旧记录沿用GLB为Y朝上、PLY/STL为Z朝上的兼容约定。
        if((frame||(extension==='glb'?'y_up':'z_up'))==='z_up')object.rotation.x=-Math.PI/2;
        if(disposed){release(object);return;}
        const bounds=new THREE.Box3().setFromObject(object);const size=bounds.getSize(new THREE.Vector3());
        const maximum=Math.max(size.x,size.y,size.z);if(!Number.isFinite(maximum)||maximum<=0)throw Error('网格范围无效');
        const center=bounds.getCenter(new THREE.Vector3());object.position.sub(center);
        const wrapper=new THREE.Group();wrapper.add(object);wrapper.scale.setScalar(2/maximum);scene.add(wrapper);
        const grid=new THREE.GridHelper(6,20,0xc0c2b9,0xdedfd8);grid.position.y=-1.05;scene.add(grid);
        renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));
        renderer.outputColorSpace=THREE.SRGBColorSpace;
        renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
        stage='hdr';setPhase('模型已解析，正在读取官方HDR环境…');
        const hdr=await new EXRLoader().loadAsync('/environment/forest.exr');
        if(disposed){hdr.dispose();return;}
        hdr.mapping=THREE.EquirectangularReflectionMapping;
        const pmrem=new THREE.PMREMGenerator(renderer);
        try{environment=pmrem.fromEquirectangular(hdr);}finally{hdr.dispose();pmrem.dispose();}
        scene.environment=environment.texture;scene.environmentIntensity=1;
        // 官方以原始Z朝上网格着色；网页为Y朝上。另补偿两渲染器经度零点的90度差。
        const lookup=new THREE.Matrix4().makeRotationY(-Math.PI/2).multiply(new THREE.Matrix4().makeRotationX(Math.PI/2));
        const rotation=new THREE.Euler().setFromRotationMatrix(lookup);
        // Three.js对环境旋转使用逐轴取负的采样矩阵。
        scene.environmentRotation.set(-rotation.x,-rotation.y,-rotation.z);
        container.replaceChildren(renderer.domElement);camera.position.set(3.3,2.6,4.5);
        controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
        const resize=()=>{if(!renderer)return;const width=container.clientWidth;const height=container.clientHeight;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();};
        observer=new ResizeObserver(resize);observer.observe(container);resize();
        renderer.setAnimationLoop(()=>{controls?.update();renderer?.render(scene,camera);});setReady(true);
      }catch(exc){if(!disposed){setProgress(null);setError((stage==='hdr'?'官方HDR环境读取失败：':stage==='parse'?'模型解析失败：':'')+(exc instanceof Error?exc.message:'模型预览不可用'));}}
    }
    void load();
    return ()=>{disposed=true;controller.abort();observer?.disconnect();controls?.dispose();renderer?.setAnimationLoop(null);environment?.dispose();renderer?.dispose();scene.traverse(release);container.replaceChildren();};
  },[run,artifact.artifact_id,artifact.relative_path,frame,attempt]);
  return <div className="viewer"><div className="canvas" ref={host}/><div className="viewer-caption">
    <div role={error?'alert':'status'}>{error||(!ready?(progress?transferLabel(progress):phase):'拖动旋转 · 滚轮缩放')}</div>
    {!ready&&!error&&progress&&<progress aria-label="模型文件读取进度" max={progress.total||undefined} value={progress.total?progress.loaded:undefined}/>}
    {error&&<button type="button" onClick={()=>setAttempt(value=>value+1)}>重新加载预览</button>}
    <span>{artifact.unit==='mm'?'毫米网格':'原始无单位网格'} · 官方forest.exr环境/PBR · 显示已归一，不作为尺寸测量</span></div></div>;
}
function release(object:THREE.Object3D){
  const mesh=object as THREE.Mesh;mesh.geometry?.dispose();
  const materials=mesh.material?Array.isArray(mesh.material)?mesh.material:[mesh.material]:[];
  for(const material of materials){for(const value of Object.values(material))if(value instanceof THREE.Texture)value.dispose();material.dispose();}
}
