from pathlib import Path
import json, hashlib, math, sys
import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
VIDEOS = [Path('D:/D26FO/Videos/屏幕录制/屏幕录制 2026-11-06 061639.mp4'),Path('D:/D26FO/Videos/屏幕录制/屏幕录制 2026-11-06 062022.mp4')]
ROOT.mkdir(parents=True, exist_ok=True)
FONT = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 20)

def metadata():
    result=[]
    for i,p in enumerate(VIDEOS,1):
        cap=cv2.VideoCapture(str(p))
        fps=cap.get(cv2.CAP_PROP_FPS)
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        result.append(dict(id=f'v{i}',source=str(p),bytes=p.stat().st_size,sha256=hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),fps=fps,frames=frames,width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),duration_seconds=frames/fps,decoder='OpenCV '+cv2.__version__,source_role='User supplied screen recording of Orca promotional website; depicted app behavior is authored demonstration, not independently exercised runtime'))
        cap.release()
    (ROOT/'metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def sample(video_id,times,prefix='sparse',cols=3,thumb_width=600):
    cap=cv2.VideoCapture(str(VIDEOS[video_id-1]))
    out=ROOT/prefix
    out.mkdir(exist_ok=True)
    images=[]
    entries=[]
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000)
        ok,frame=cap.read()
        if not ok: continue
        img=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        name=f'v{video_id}_{float(t):07.3f}s.jpg'
        img.save(out/name,quality=93)
        h=round(img.height*thumb_width/img.width)
        thumb=img.resize((thumb_width,h))
        tile=Image.new('RGB',(thumb_width,h+32),'#242424')
        tile.paste(thumb,(0,32))
        ImageDraw.Draw(tile).text((10,4),f'V{video_id}  {t:07.3f}s',font=FONT,fill='white')
        images.append(tile)
        entries.append({'video_id':video_id,'time_seconds':t,'frame_file':str(out/name),'sampling':'ordered stills; no natural speed playback'})
    cap.release()
    if images:
        max_h=max(im.height for im in images)
        # Bounded contact sheets preserve large enough whole-frame context.
        for part in range(0,len(images),12):
            batch=images[part:part+12]
            sheet=Image.new('RGB',(cols*thumb_width,math.ceil(len(batch)/cols)*max_h),'#444444')
            for j,im in enumerate(batch): sheet.paste(im,((j%cols)*thumb_width,(j//cols)*max_h))
            sheet.save(out/f'v{video_id}_sheet_{part//12+1}.jpg',quality=94)
    (out/f'v{video_id}_frames.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'video':video_id,'prefix':prefix,'count':len(entries),'sheets':math.ceil(len(images)/12)}))

if __name__=='__main__':
    if len(sys.argv)==1:
        meta=metadata()
        for row in meta:
            times=list(range(0,int(row['duration_seconds']),8))
            times.append(round(row['duration_seconds']-.2,3))
            sample(int(row['id'][-1]),times)
    else:
        sample(int(sys.argv[1]),json.loads(sys.argv[2]),sys.argv[3])
