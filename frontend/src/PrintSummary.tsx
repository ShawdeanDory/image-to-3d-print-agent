import type {MeshInspection,PrinterProfile} from './contracts.generated';
import {checkNames} from './domain';
import './print-summary.css';

export function estimatePrint(inspection:MeshInspection,profile:PrinterProfile){
  const self=inspection.checks?.find(c=>c.name==='self_intersection');
  const validVolume=inspection.unit==='mm'&&inspection.watertight&&inspection.normals_consistent
    &&inspection.boundary_edge_count===0&&inspection.non_manifold_edge_count===0&&inspection.non_manifold_vertex_count===0
    &&inspection.component_count===1&&self?.status==='pass'&&self.value===0
    &&typeof inspection.volume_mm3==='number'&&Number.isFinite(inspection.volume_mm3)&&inspection.volume_mm3>=0;
  const height=inspection.unit==='mm'?inspection.dimensions_mm?.[2]:undefined;
  const layers=typeof height==='number'&&Number.isFinite(height)&&height>0&&profile.layer_height_mm>0
    ?Math.max(1,Math.ceil(height/profile.layer_height_mm-1e-6)):null;
  return {solidGrams:validVolume?inspection.volume_mm3!/1000*1.24:null,
    volumeCm3:validVolume?inspection.volume_mm3!/1000:null,layers};
}

export default function PrintSummary({inspection,profile}:{inspection:MeshInspection;profile:PrinterProfile}){
  const {solidGrams,volumeCm3,layers}=estimatePrint(inspection,profile);
  const checks=inspection.checks??[];
  const wall=checks.find(c=>c.name==='wall_thickness');
  const overhang=checks.find(c=>c.name==='overhang');
  const issues=checks.filter(c=>c.status==='fail'||c.status==='not_run');
  const wallText=wall?.status==='pass'?`抽样未发现低于${profile.min_wall_mm}mm的薄壁`
    :wall?.status==='fail'?'发现局部薄壁':wall?.status==='warn'?'阈值附近需复核':'未执行';
  let volumeReason=inspection.volume_reason||'缺少可靠实体体积';
  if(inspection.component_count>1)volumeReason='多个壳体可能重叠或嵌套，不能直接累加体积';
  else if(!inspection.watertight)volumeReason='网格未封闭，实体体积不可靠';
  else if(checks.find(c=>c.name==='self_intersection')?.status!=='pass')volumeReason='自交检查未通过或未执行';
  return <div className="print-summary">
    <p className={'print-summary-verdict '+(issues.length?'blocked':'review')} role="status">{issues.length
      ?'尚不能确认可打印：'+issues.map(c=>checkNames[c.name]||c.name).join('、')
      :'检查结果见下表，按实际打印机切片核对支撑和耗材。'}</p>
    <dl>
      <div><dt>尺寸</dt><dd>{inspection.unit==='mm'&&inspection.dimensions_mm?inspection.dimensions_mm.map(n=>n.toFixed(2)).join(' × ')+'mm':'未知'}</dd><small>打印方向Z朝上</small></div>
      <div><dt>水密 / 壳体</dt><dd>{inspection.watertight?'是':'否'} / {inspection.component_count}个</dd><small>边界边{inspection.boundary_edge_count}条</small></div>
      <div><dt>名义层数</dt><dd>{layers??'未知'}</dd><small>按{profile.layer_height_mm}mm层高，不含支撑附加层</small></div>
      <div><dt>可靠实体体积</dt><dd>{volumeCm3===null?'未知':volumeCm3.toFixed(2)+'cm³'}</dd><small>{volumeCm3===null?volumeReason:'封闭单实体、方向和自交证据有效'}</small></div>
      <div><dt>100%实体PLA换算</dt><dd>{solidGrams===null?'无法可靠估算':solidGrams.toFixed(1)+'g'}</dd><small>密度按1.24g/cm³；不是切片耗材</small></div>
      <div><dt>实际打印耗材</dt><dd>切片后确定</dd><small>取决于外壁、顶底层、填充率与支撑</small></div>
      <div><dt>局部薄壁检查</dt><dd>{wallText}</dd><small>{wall?.status==='not_run'?String(wall.details?.reason||'缺检查证据'):'局部射线抽样；不是全局最小壁厚'}</small></div>
      <div><dt>悬垂</dt><dd>{overhang?.status==='not_run'||!overhang?'未执行':typeof overhang.value==='number'?overhang.value+'面':'见逐项报告'}</dd><small>{overhang?.status==='warn'?'存在支撑风险，切片时核对':overhang?.status==='pass'?'当前阈值未检出悬垂':'检查依据见下表'}</small></div>
    </dl>
    <p className="print-summary-note">闭合实体不等于100%实心打印。此处不使用总体积/表面积比替代局部薄壁检查；实际耗材以同版本模型的切片结果为准。</p>
  </div>;
}
