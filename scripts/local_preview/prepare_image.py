"""为本机试用准备透明PNG；普通照片用已安装rembg在本机去背景。"""
import json
from pathlib import Path
import sys

from PIL import Image, ImageOps


source, target = map(Path, sys.argv[1:3])
with Image.open(source) as original:
    image = ImageOps.exif_transpose(original).convert("RGBA")
alpha = image.getchannel("A")
if alpha.getbbox() is None:
    raise ValueError("图片完全透明，没有可重建主体")
method = "existing_alpha"
if alpha.getextrema()[0] == 255:
    import rembg
    print("正在准备u2net并自动去背景；照片只在本机处理。", flush=True)
    session = rembg.new_session("u2net", providers=["CPUExecutionProvider"])
    image = rembg.remove(image, session=session).convert("RGBA")
    method = "rembg_u2net_cpu"
if image.getchannel("A").getbbox() is None:
    raise ValueError("去背景后没有主体，请换一张主体更清楚的图片")
if image.getchannel("A").getextrema()[0] == 255:
    raise ValueError("未得到透明背景，不能进入当前重建入口")
image.save(target)
print(json.dumps({"method": method, "prepared_image": str(target), "size": image.size}, ensure_ascii=False))
