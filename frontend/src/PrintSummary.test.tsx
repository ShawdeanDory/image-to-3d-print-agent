import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import PrintSummary,{estimatePrint} from './PrintSummary';
import type {MeshInspection,PrinterProfile} from './contracts.generated';
const profile={layer_height_mm:.2,min_wall_mm:1.2,material:'PLA'} as PrinterProfile;
function closed():MeshInspection{return {mesh_version:'m_fixture',unit:'mm',dimensions_mm:[10,10,10],volume_mm3:1000,
  component_count:1,watertight:true,normals_consistent:true,boundary_edge_count:0,non_manifold_edge_count:0,non_manifold_vertex_count:0,
  checks:[{name:'self_intersection',status:'pass',value:0},{name:'wall_thickness',status:'pass',value:1.2,threshold:1.2}]} as MeshInspection;}
it('可靠单实体只作100%实体换算，不冒充切片耗材；薄壁数值不是最小厚度',()=>{
  const result=estimatePrint(closed(),profile);
  expect(result.solidGrams).toBeCloseTo(1.24);expect(result.layers).toBe(50);
  const html=renderToStaticMarkup(<PrintSummary inspection={closed()} profile={profile}/>);
  expect(html).toContain('100%实体PLA换算');expect(html).toContain('切片后确定');
  expect(html).toContain('抽样未发现低于1.2mm');expect(html).toContain('不是全局最小壁厚');
});
it('开孔、自交、多壳和缺检查均不显示可靠重量，防止重复计体积',()=>{
  for(const patch of [{watertight:false},{component_count:2},{checks:[]},{checks:undefined},{unit:'unitless'},
    {checks:[{name:'self_intersection',status:'fail',value:2}]}]){
    expect(estimatePrint({...closed(),...patch} as MeshInspection,profile).solidGrams).toBeNull();
  }
});
it('薄壁未执行不显示通过；未知尺度不推算层数',()=>{
  const inspection={...closed(),volume_mm3:null,volume_reason:'网格未封闭',watertight:false,
    checks:[{name:'wall_thickness',status:'not_run',value:null,details:{reason:'网格未封闭'}}]} as MeshInspection;
  const html=renderToStaticMarkup(<PrintSummary inspection={inspection} profile={profile}/>);
  expect(html).toContain('未执行');expect(html).toContain('网格未封闭');
  expect(html).not.toContain('29.19');expect(html).not.toContain('2001.9');
  expect(estimatePrint({...closed(),unit:'unitless'},profile).layers).toBeNull();
});
it('极小正高度至少1层，浮点整数高度不多估1层',()=>{
  expect(estimatePrint({...closed(),dimensions_mm:[1,1,1e-9]},profile).layers).toBe(1);
  expect(estimatePrint({...closed(),dimensions_mm:[1,1,120.00000001]},profile).layers).toBe(600);
});
