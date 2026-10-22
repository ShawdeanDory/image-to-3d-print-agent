import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {PLYLoader} from 'three/addons/loaders/PLYLoader.js';
import {STLLoader} from 'three/addons/loaders/STLLoader.js';
import {EXRLoader} from 'three/addons/loaders/EXRLoader.js';
import type {ArtifactRecord} from './contracts.generated';
import {artifactBlob} from './api';

export default function ModelView({run,artifact,frame}:{run:string;artifact:ArtifactRecord;frame?:'z_up'|'y_up'}) {
  const host=useRef<HTMLDivElement>(null);const [error,setError]=useState('');const [ready,setReady]=useState(false);
  useEffect(()=>{
    const container=host.current!;let disposed=false;let renderer:THREE.WebGLRenderer|undefined;
    let object:THREE.Object3D|undefined;let controls:OrbitControls|undefined;let observer:ResizeObserver|undefined;
    let environment:THREE.WebGLRenderTarget|undefined;
    setReady(false);setError('');
    const scene=new THREE.Scene();scene.background=new THREE.Color('#eeeee9');
    const camera=new THREE.PerspectiveCamera(40,1,.01,100);
    async function load() {
      try {
        const data=await (await artifactBlob(run,artifact.artifact_id)).arrayBuffer();
        if(disposed)return;
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
      }catch(exc){if(!disposed)setError(exc instanceof Error?exc.message:'模型预览不可用');}
    }
    void load();
    return ()=>{disposed=true;observer?.disconnect();controls?.dispose();renderer?.setAnimationLoop(null);environment?.dispose();renderer?.dispose();scene.traverse(release);container.replaceChildren();};
  },[run,artifact.artifact_id,artifact.relative_path,frame]);
  return <div className="viewer"><div className="canvas" ref={host}/><div className="viewer-caption">{error||(!ready?'正在读取本任务模型和官方HDR…':'拖动旋转 · 滚轮缩放')}<span>{artifact.unit==='mm'?'毫米网格':'原始无单位网格'} · 官方forest.exr环境/PBR · 显示已归一，不作为尺寸测量</span></div></div>;
}
function release(object:THREE.Object3D){
  const mesh=object as THREE.Mesh;mesh.geometry?.dispose();
  const materials=mesh.material?Array.isArray(mesh.material)?mesh.material:[mesh.material]:[];
  for(const material of materials){for(const value of Object.values(material))if(value instanceof THREE.Texture)value.dispose();material.dispose();}
}
