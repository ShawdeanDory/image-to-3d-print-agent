import { describe, expect, it } from 'vitest';
import { checkLabel, validateImage, heightNumber, mergeEvents, newSubmission, artifactGroups, checkMeasure } from './domain';
import type { PendingInput, RuntimeEvent, ArtifactRecord } from './contracts.generated';

describe('页面沿用后端语义', () => {
  it('未执行不能当通过，未知高度不填0', () => {
    expect(checkLabel('not_run')).toBe('未执行');
    expect(heightNumber('')).toBeNull();
    expect(() => heightNumber('-1')).toThrow();
    expect(() => heightNumber('NaN')).toThrow();
  });
  it('悬垂面数与角度分开，布尔结果不拼尺寸单位',()=>{
    expect(checkMeasure('overhang',4492,'degree')).toBe('4492面');
    expect(checkMeasure('overhang',45,'degree',true)).toBe('45°');
    expect(checkMeasure('build_volume',true,'mm')).toBe('是');
  });
  it('限制图片大小与类型，最终格式仍由服务端核验', () => {
    expect(() => validateImage({name: 'a.png', type: 'image/png', size: 10485761})).toThrow();
    expect(() => validateImage({name: 'a.svg', type: 'image/svg+xml', size: 10})).toThrow();
    expect(validateImage({name: 'a.jpg', type: 'image/jpeg', size: 100})).toBeUndefined();
  });
  it('按事件ID去重，拒绝其他任务事件', () => {
    const event = {event_id: 2, run_id: 'run1'} as RuntimeEvent;
    expect(mergeEvents([event], [event], 'run1')).toHaveLength(1);
    expect(() => mergeEvents([], [event], 'other')).toThrow();
  });
  it('每次确认绑定等待项与版本，不能由字段覆盖', () => {
    const pending = {kind:'print_review', pending_input_id:'i_now', mesh_version:'m_now'} as PendingInput;
    const input = newSubmission(pending, {bed_confirmed:true, mesh_version:'m_old', kind:'slicer'}, 's_fixed');
    expect(input).toMatchObject({kind:'print_review',mesh_version:'m_now',pending_input_id:'i_now',submission_id:'s_fixed'});
  });
  it('仅本任务登记模型进入预览，不把日志当下载或预存模型', () => {
    const a = {run_id:'r',kind:'raw_mesh',relative_path:'runs/r/raw.ply',artifact_id:'a'} as ArtifactRecord;
    expect(artifactGroups([a], 'r').models).toHaveLength(1);
    expect(() => artifactGroups([a], 'other')).toThrow();
  });
});
