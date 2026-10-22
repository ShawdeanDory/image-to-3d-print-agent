"""复用TRELLIS.2环境执行几何GPU补片，不加载生成模型或访问网络。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.geometry.gpu_holes import repair_gpu_mesh


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve() or args.output.exists():raise ValueError('拒绝覆盖源文件或已有候选')
    import numpy as np,torch,trimesh
    from scipy.spatial import cKDTree
    source=trimesh.load(args.input,force='mesh',process=False)
    if len(source.faces)>17000000:raise ValueError('网格超过本轮GPU资源范围')
    v=torch.tensor(np.asarray(source.vertices),dtype=torch.float32,device='cuda')
    f=torch.tensor(np.asarray(source.faces),dtype=torch.int32,device='cuda')
    v,f,report=repair_gpu_mesh(v,f)
    result=trimesh.Trimesh(v.cpu().numpy(),f.cpu().numpy(),process=False)
    if source.visual.kind=='vertex':
        colors=np.asarray(source.visual.vertex_colors)
        if len(v)>len(source.vertices):
            ids=cKDTree(source.vertices).query(result.vertices[len(colors):],k=min(4,len(colors)))[1]
            if ids.ndim==1:ids=ids[:,None]
            colors=np.r_[colors,np.round(colors[ids].mean(1)).astype(np.uint8)]
        result.visual=trimesh.visual.ColorVisuals(result,vertex_colors=colors)
        report['new_vertex_color']='nearest_boundary_color_approximation'
    result.export(args.output)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
