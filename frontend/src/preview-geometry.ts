import * as THREE from 'three';

export type StandardView='perspective'|'front'|'back'|'top'|'bottom'|'left'|'right';

export function preparePreview(object:THREE.Object3D,frame:'y_up'|'z_up'){
  // 只变换显示父节点，不改源顶点、原节点变换、材质或下载文件。
  const axis=new THREE.Group();axis.add(object);
  if(frame==='z_up')axis.rotation.x=-Math.PI/2;
  axis.updateMatrixWorld(true);
  const bounds=new THREE.Box3().setFromObject(axis),size=bounds.getSize(new THREE.Vector3());
  const maximum=Math.max(size.x,size.y,size.z);
  if(!Number.isFinite(maximum)||maximum<=0)throw Error('模型为空或包围盒无效');
  axis.position.sub(bounds.getCenter(new THREE.Vector3()));
  const root=new THREE.Group();root.add(axis);root.scale.setScalar(2/maximum);root.updateMatrixWorld(true);
  const displayBounds=new THREE.Box3().setFromObject(root);
  return {root,floorY:displayBounds.min.y,radius:displayBounds.getBoundingSphere(new THREE.Sphere()).radius};
}

export function viewPose(view:StandardView,radius:number,fov:number,aspect:number){
  const angle=Math.min(THREE.MathUtils.degToRad(fov),2*Math.atan(Math.tan(THREE.MathUtils.degToRad(fov)/2)*aspect));
  const distance=radius/Math.sin(angle/2)*1.12;
  const directions:Record<StandardView,[number,number,number]>={perspective:[2.6,1.6,3.7],front:[0,0,1],back:[0,0,-1],top:[0,1,0],bottom:[0,-1,0],left:[-1,0,0],right:[1,0,0]};
  return {position:new THREE.Vector3(...directions[view]).normalize().multiplyScalar(distance),
    up:view==='top'?new THREE.Vector3(0,0,-1):view==='bottom'?new THREE.Vector3(0,0,1):new THREE.Vector3(0,1,0),target:new THREE.Vector3()};
}

export function modelStats(object:THREE.Object3D){
  let vertices=0,triangles=0;const materials=new Set<THREE.Material>();
  object.traverse(node=>{
    const mesh=node as THREE.Mesh;if(!mesh.isMesh)return;
    vertices+=mesh.geometry.attributes.position?.count||0;
    triangles+=(mesh.geometry.index?.count??mesh.geometry.attributes.position?.count??0)/3;
    for(const m of Array.isArray(mesh.material)?mesh.material:[mesh.material])materials.add(m);
  });
  return {vertices,triangles,materials:materials.size};
}
