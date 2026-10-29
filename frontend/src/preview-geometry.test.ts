import {expect,it} from 'vitest';
import * as THREE from 'three';
import {preparePreview,viewPose,modelStats} from './preview-geometry';

it('Z朝上的STL和对应Y朝上GLB显示同向、居中，源顶点不变',()=>{
  const shape=new THREE.BoxGeometry(151,119,120);shape.translate(42,-18,60);
  const stl=new THREE.Mesh(shape);const before=Array.from(shape.attributes.position.array);
  const glb=new THREE.Group();const copy=stl.clone();copy.rotation.x=-Math.PI/2;copy.scale.setScalar(.001);glb.add(copy);
  const a=preparePreview(stl,'z_up');const b=preparePreview(glb,'y_up');
  const ab=new THREE.Box3().setFromObject(a.root),bb=new THREE.Box3().setFromObject(b.root);
  expect(ab.getCenter(new THREE.Vector3()).length()).toBeLessThan(1e-10);
  expect(bb.getCenter(new THREE.Vector3()).length()).toBeLessThan(1e-10);
  expect(ab.getSize(new THREE.Vector3()).distanceTo(bb.getSize(new THREE.Vector3()))).toBeLessThan(1e-10);
  expect(a.floorY).toBeCloseTo(ab.min.y);expect(a.floorY).not.toBe(-1.05);
  expect(Array.from(shape.attributes.position.array)).toEqual(before);
  expect(stl.position.toArray()).toEqual([0,0,0]);expect(stl.rotation.x).toBe(0);
});

it('六向视图围绕中心，顶/底视图相机上方向不与视线平行',()=>{
  for(const view of ['front','back','top','bottom','left','right'] as const){
    const pose=viewPose(view,1.4,40,.5);
    expect(pose.target.toArray()).toEqual([0,0,0]);
    expect(pose.position.clone().normalize().cross(pose.up).length()).toBeGreaterThan(.99);
    expect(pose.position.length()).toBeGreaterThan(1.4);
  }
  expect(viewPose('front',1.4,40,.5).position.z).toBeGreaterThan(viewPose('front',1.4,40,2).position.z);
});

it('模型统计来自实际几何；空几何明确拒绝',()=>{
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,2,3),new THREE.MeshStandardMaterial());
  expect(modelStats(mesh)).toMatchObject({vertices:24,triangles:12,materials:1});
  expect(()=>preparePreview(new THREE.Group(),'y_up')).toThrow();
});
