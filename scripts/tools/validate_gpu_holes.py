"""固定GPU算子验证；不加载模型、不调用LLM、不执行PBR烘焙。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--real-glb',type=Path);args=parser.parse_args()
    import numpy as np,torch,trimesh,cumesh
    from image_to_3d_print.geometry.gpu_holes import repair_gpu_mesh,before_pbr_export
    args.output.mkdir(parents=True,exist_ok=True)
    box=trimesh.creation.box(extents=[20,20,20])
    for _ in range(6):box=trimesh.Trimesh(*trimesh.remesh.subdivide(box.vertices,box.faces),process=False)
    centers=box.triangles_center
    keep=~((centers[:,2]>9.99)&(np.abs(centers[:,0])<.3)&(np.abs(centers[:,1])<.3))
    hole=trimesh.Trimesh(box.vertices,box.faces[keep],process=False)
    hole.visual.vertex_colors=np.tile([190,130,60,255],(len(hole.vertices),1))
    hole.export(args.output/'fixture-eight-edge-hole.ply')
    cases={'eight_edge_boundary':(hole,True),
        'closed_design_opening':(trimesh.creation.annulus(r_min=3,r_max=5,height=2,sections=32),False),
        'oversized_open_box':(trimesh.Trimesh(box.vertices,box.faces[centers[:,2]<9.99],process=False),False)}
    records={}
    for label,(mesh,expected) in cases.items():
        vertices=torch.tensor(np.asarray(mesh.vertices),device='cuda',dtype=torch.float32)
        faces=torch.tensor(np.asarray(mesh.faces),device='cuda',dtype=torch.int32)
        v,f,result=repair_gpu_mesh(vertices,faces)
        assert (result['status']=='applied')==expected,label
        records[label]=result
        if expected:
            _,_,again=repair_gpu_mesh(v,f);assert again['added_faces']==0;records['idempotent_repeat']=again
            cu=cumesh.CuMesh();cu.init(vertices,faces);reports=[];original=cumesh.CuMesh.uv_unwrap
            with before_pbr_export(reports):
                uv=cu.uv_unwrap(return_vmaps=True,verbose=False)
            assert cumesh.CuMesh.uv_unwrap is original and reports[0]['added_faces']==8
            records['actual_uv_hook']={'added_faces':reports[0]['added_faces'],'uv_return_count':len(uv),'hook_restored':True,'pbr_bake':'not_run'}
    invalid_v=torch.zeros((3,3),device='cuda');invalid_f=torch.tensor([[0,1,9]],dtype=torch.int32,device='cuda')
    try:repair_gpu_mesh(invalid_v,invalid_f)
    except ValueError:records['invalid_index']={'rejected':True}
    else:raise AssertionError('坏索引没有拒绝')
    try:repair_gpu_mesh(invalid_v.cpu(),torch.tensor([[0,1,2]],dtype=torch.int32))
    except RuntimeError:records['cpu_fallback']={'rejected':True}
    else:raise AssertionError('不允许回退CPU')
    if args.real_glb:
        mesh=trimesh.load(args.real_glb,force='mesh',process=False)
        vertices,inverse=np.unique(np.asarray(mesh.vertices,dtype=np.float32),axis=0,return_inverse=True)
        v,f,result=repair_gpu_mesh(torch.tensor(vertices,device='cuda'),torch.tensor(inverse[mesh.faces],device='cuda',dtype=torch.int32))
        records['real_glb']=result
        trimesh.Trimesh(v.cpu().numpy(),f.cpu().numpy(),process=False).export(args.output/'real-boundary-candidate.ply')
    records['scope']={'origin':'test_fixture_and_optional_user_glb','model_generation':'not_run','pbr_bake':'not_run','semantic_completion':'not_run','gpu':torch.cuda.get_device_name(0)}
    (args.output/'validation.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False))


if __name__=='__main__':main()
