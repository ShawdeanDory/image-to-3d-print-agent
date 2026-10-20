"""整理固定清单和异常样例；只做CPU图片/文本准备，不运行模型。"""
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw

root=Path(__file__).resolve().parents[2]
base=root/"fixtures/p1";(base/"masks").mkdir(parents=True,exist_ok=True);(base/"boundary").mkdir(exist_ok=True)
def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def request(asset):
    return {"image_asset_id":asset,"height_value":80,"height_unit":"mm","scale_source":"user_target","orientation":{"up_axis":"z","confirmed":True},"printer_profile_id":"demo_v1"}
sets={"development":["hamburger","robot","block","pyramid","bead","knob"],"evaluation":["cone","octahedron","ring","stairs","tower","mushroom"],"holdout":["arch","cross","spool","trophy","pedestal","toy_house"]}
normal={};assets={};cases=[]
for split,names in sets.items():
    label={"development":"dev","evaluation":"eval","holdout":"hold"}[split]
    for i,name in enumerate(names,1):
        old=name in {"hamburger","robot"}
        path=(root/"fixtures/p0" if old else base/"procedural")/(name+".png")
        with Image.open(path) as image:
            rgba=image.convert("RGBA");rgba.getchannel("A").point(lambda p:255 if p>=128 else 0).save(base/"masks"/(name+".png"))
            assets["asset_"+name]={"asset_id":"asset_"+name,"relative_path":path.relative_to(root).as_posix(),"content_type":"image/png","byte_count":path.stat().st_size,"width":image.width,"height":image.height}
        case={"case_id":label+"_n"+str(i).zfill(2),"split":split,"category":"normal","object_group":("p0_" if old else "procedural_")+name,"asset_path":path.relative_to(root).as_posix(),"mask_path":"fixtures/p1/masks/"+name+".png","source_kind":"authorized_p0" if old else "procedural_cpu","source_ref":"TripoSR@107cefdc244c39106fa830359024f6a2f1c78871/examples/"+name+".png" if old else "scripts/p1/build_fixture_images.py@1.0.0:"+name,"license":"MIT-source-repository; original-image-author-unverified" if old else "CC0-1.0","image_should_decode":True,"request_should_validate":True,"request":request("asset_"+name),"expected":"candidate","expected_reason":"后续生成非空、有限坐标且可独立读取的候选网格；打印合格另验收","result_status":"not_run"}
        normal[name]=case;cases.append(case)
# 文件边界输入不向有效asset注册表冒充上传成功。
(base/"boundary/corrupt.png").write_bytes(b"P1 intentionally corrupted image")
Image.new("RGB",(32,32),(60,90,120)).save(base/"boundary/spoofed.png",format="BMP")
person=Image.new("RGBA",(256,256),(255,255,255,0));draw=ImageDraw.Draw(person);draw.ellipse((100,20,156,76),fill="navy");draw.rectangle((110,76,146,180),fill="navy");draw.line((110,90,60,140),fill="navy",width=15);draw.line((146,90,196,140),fill="navy",width=15);draw.line((120,170,90,240),fill="navy",width=15);draw.line((136,170,166,240),fill="navy",width=15);person.save(base/"boundary/person.png")
with Image.open(base/"procedural/ring.png") as original:
    background=Image.new("RGBA",original.size,"white");draw=ImageDraw.Draw(background)
    for x in range(0,256,16):
        for y in range(0,256,16):
            if (x+y)//16%2:draw.rectangle((x,y,x+15,y+15),fill=(180,130,70,255))
    Image.alpha_composite(background,original.convert("RGBA")).save(base/"boundary/background.png")
with Image.open(base/"procedural/arch.png") as original:
    occluded=original.convert("RGBA");ImageDraw.Draw(occluded).rectangle((100,60,255,230),fill=(255,255,255,255));occluded.save(base/"boundary/occluded.png")
def boundary(split,number,name,expected,reason,changes=None,path=None,decodes=True):
    source=normal[name];label={"development":"dev","evaluation":"eval","holdout":"hold"}[split]
    case=dict(source);case.update(case_id=label+"_b"+str(number).zfill(2),category="boundary",expected=expected,expected_reason=reason,mask_path=None)
    case["request"]=dict(source["request"])
    if changes:case["request"].update(changes)
    if path:
        case.update(asset_path="fixtures/p1/boundary/"+path,source_kind="boundary_fixture",source_ref="scripts/p1/prepare_fixture_manifest.py@1.0.0:"+path,license="CC0-1.0",image_should_decode=decodes)
    return case
extra=[boundary("development",1,"block","wait","请求补齐高度和单位",{"height_value":None,"height_unit":None}),boundary("development",2,"pyramid","reject","INVALID_IMAGE：上传内容损坏",path="corrupt.png",decodes=False),boundary("development",3,"bead","reject","人物不在第一版物体范围；语义判断待后续实现",path="person.png"),boundary("development",4,"knob","tool_failure","TOOL_UNAVAILABLE；不得编造成功"),boundary("evaluation",1,"cone","wait","单位缺失，不能定标",{"height_unit":None}),boundary("evaluation",2,"ring","review","复杂背景需要前景复核，不预设算法结果",path="background.png"),boundary("evaluation",3,"octahedron","wait","打印空间未知，不能确认build_volume通过",{"printer_profile_id":"demo_unknown_space"}),boundary("evaluation",4,"stairs","tool_failure","TOOL_TIMEOUT；实际工具未执行"),boundary("holdout",1,"arch","review","主体遮挡，需换图或人工复核",path="occluded.png"),boundary("holdout",2,"cross","reject","真实BMP伪装PNG，上传格式拒绝",path="spoofed.png",decodes=False),boundary("holdout",3,"spool","wait","姿态未确认，不能定标",{"orientation":{}}),boundary("holdout",4,"trophy","wait","尺度来源未知，需追问",{"scale_source":None})]
for case in extra:
    if not case["image_should_decode"]:
        case["request"]["image_asset_id"]="pending_upload_"+case["case_id"]
    if case["asset_path"]!=normal[next(name for name,c in normal.items() if c["object_group"]==case["object_group"])]["asset_path"]:
        # 同源遮挡/背景变体继续保留对象组，防止跨划分泄漏。
        if case["image_should_decode"]:
            aid=case["case_id"]+"_asset";case["request"]["image_asset_id"]=aid
            path=root/case["asset_path"]
            with Image.open(path) as im:assets[aid]={"asset_id":aid,"relative_path":case["asset_path"],"content_type":"image/png","byte_count":path.stat().st_size,"width":im.width,"height":im.height}
cases+=extra
order={"development":0,"evaluation":1,"holdout":2};cases.sort(key=lambda c:(order[c["split"]],c["category"]!="normal",c["case_id"]))
dump(root/"evals/dataset_v1.json",{"schema_version":"1.0.0","dataset_version":"1.0.0","policy":{"cases_per_split":10,"normal_per_split":6},"scope":"P1固定契约与受控生成测试集：2张已见P0图片+16个项目自产CPU渲染对象；不能据此推断自然图片泛化。保留集本轮仅静态检查，无模型评估。","cases":cases})
dump(base/"assets.json",list(assets.values()))
unknown=json.loads((base/"printer_profile.json").read_text(encoding="utf-8"));unknown.update(profile_id="demo_unknown_space",build_volume_mm=None);dump(base/"printer_profile_unknown.json",unknown)
# 成功响应样例中的文件仅为契约fixture，不能当作真实切片/模型评估。
dump(base/"contracts/inspection_fixture.json",{"fixture_only":True,"message":"人工设计的契约数据，没有执行网格检查"})
dump(base/"contracts/slicer_fixture.json",{"fixture_only":True,"message":"人工设计的契约数据，没有执行切片"})
preview=Image.new("RGB",(64,64),"white");ImageDraw.Draw(preview).rectangle((15,15,49,49),outline="blue",width=2);preview.save(base/"contracts/preview_fixture.png")
# 简单长方体STL只作为路径/类型引用的固定文件，不作为切片通过证据。
verts=[(x,y,z) for z in (0,80) for y in (0,40) for x in (0,40)]
faces=[(0,2,1),(1,2,3),(4,5,6),(5,7,6),(0,1,4),(1,5,4),(2,6,3),(3,6,7),(0,4,2),(2,4,6),(1,3,5),(3,7,5)]
lines=["solid contract_fixture"]
for face in faces:
    lines += ["facet normal 0 0 0","outer loop"]+["vertex %s %s %s"%verts[i] for i in face]+["endloop","endfacet"]
(base/"contracts/candidate_fixture.stl").write_text("\n".join(lines+["endsolid contract_fixture"])+"\n",encoding="ascii")
print(json.dumps({"cases":len(cases),"normal":sum(c["category"]=="normal" for c in cases),"boundary":sum(c["category"]=="boundary" for c in cases),"valid_assets":len(assets)},ensure_ascii=False))
