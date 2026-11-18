from pathlib import Path
import csv, json, shutil, hashlib, math
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).parent
OUT=ROOT/'curated'
OUT.mkdir(exist_ok=True)
selected=[
 ('episode-orchestration',1,2,'workers-started'),
 ('episode-orchestration',1,8,'parallel-work'),
 ('episode-orchestration',1,10,'worker-report'),
 ('sparse',1,16,'chat-terminal-files'),
 ('sparse',1,32,'cli-agent'),
 ('episode-browser',1,40,'feedback-mode'),
 ('episode-browser',1,43,'element-annotation'),
 ('episode-browser',1,45,'feedback-recipient'),
 ('episode-browser',1,48,'feedback-in-chat'),
 ('episode-git-review',1,56,'staged-commit'),
 ('episode-git-review',1,64,'pr-checks-review'),
 ('episode-git-review',1,72,'review-to-agent'),
 ('sparse',1,80,'plugins'),
 ('episode-phone',1,96,'phone-desktop-result'),
 ('episode-chat-terminal',2,34,'chat-to-terminal-menu'),
 ('episode-chat-terminal',2,38,'terminal-context-result'),
 ('episode-chat-terminal',2,40,'terminal-to-chat-menu'),
 ('episode-chat-terminal',2,42,'chat-context-result'),
 ('episode-remote',2,53,'host-selection'),
 ('episode-remote',2,59,'remote-worktree-task'),
 ('sparse',2,96,'split-terminal'),
 ('sparse',2,104,'issue-to-worktree'),
 ('sparse',2,120,'markdown-editor'),
 ('episode-notes',2,129,'line-note-entry'),
 ('episode-notes',2,136,'line-note-to-agent'),
]
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',19)
tiles=[]
manifest=[]
for n,(directory,vid,t,label) in enumerate(selected,1):
    src=ROOT/directory/f'v{vid}_{t:07.3f}s.jpg'
    name=f'{n:02d}_v{vid}_{t:07.3f}s_{label}.jpg'
    dest=OUT/name
    shutil.copy2(src,dest)
    img=Image.open(dest).convert('RGB')
    width=600
    height=round(width*img.height/img.width)
    tile=Image.new('RGB',(width,425),'#303030')
    tile.paste(img.resize((width,height)),(0,32))
    ImageDraw.Draw(tile).text((7,5),f'{n:02d}  V{vid} {t:06.2f}s  {label}',font=font,fill='white')
    tiles.append(tile)
    manifest.append(dict(id=f'F{n:02d}',video=f'V{vid}',requested_seek_seconds=t,source_derivative=str(src.relative_to(ROOT)),file=str(dest.relative_to(ROOT)),sha256=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest(),label=label,role='Timestamped whole frame of website promotional demonstration; not actual app runtime verification'))
for start in range(0,len(tiles),9):
    batch=tiles[start:start+9]
    sheet=Image.new('RGB',(1800,425*math.ceil(len(batch)/3)),'#303030')
    for j,tile in enumerate(batch): sheet.paste(tile,((j%3)*600,(j//3)*425))
    sheet.save(OUT/f'curated_sheet_{start//9+1}.jpg',quality=94)
(ROOT/'curated-frames.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
screens=[]
for i,token in enumerate(['ee005c37-6897-4ae5-b1c1-790d45b3fb61','d2480cc6-549b-4810-b04a-cb3f63a45cd2','c94ebbb9-f491-498e-8876-d02b89a23ea3'],1):
    src=Path('C:/Users/D26FO/AppData/Local/Temp')/f'codex-clipboard-{token}.png'
    dest=ROOT/f'source-screenshot-{i}.png'
    shutil.copy2(src,dest)
    img=Image.open(dest)
    screens.append(dict(id=f'S{i}',source=str(src),file=dest.name,bytes=dest.stat().st_size,width=img.width,height=img.height,sha256=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest(),role='User supplied website feature inventory or feature detail still; no temporal claims'))
(ROOT/'screenshot-metadata.json').write_text(json.dumps(screens,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(curated_frames=len(manifest),curated_sheets=3,source_screenshots=len(screens))))
