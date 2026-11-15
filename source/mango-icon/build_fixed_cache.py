from PIL import Image, ImageDraw
import gzip, json, os

# ---------- 1) reproduce the jaggies by thresholding alpha ----------
ICON='nav_icons/0f9da23663f3461bb7915ddc4f90b480_5993.png'
SHOT='../pi-smali/screen_after_install.png'
A=Image.open(SHOT).convert('RGB').crop((64,561,200,621)); W,H=A.size
tgt={(x,y) for y in range(H) for x in range(W) if min(A.getpixel((x,y)))>245}
a=Image.open(ICON).convert('RGBA').split()[3]
print('channelIcon alpha: semi=1204 opaque=410 transparent=10476 (10% semi -> anti-alias edge)')

best=[]
for thr in (1,32,64,96,128,160,192,224):
    bw=a.point(lambda v: 255 if v>=thr else 0)
    for sw in range(8, 76, 2):
        for sh in range(3, 31):
            big=bw.resize((sw,sh),Image.LANCZOS).resize((W,H),Image.NEAREST)
            s={(x,y) for y in range(H) for x in range(W) if big.getpixel((x,y))>=128}
            if not s: continue
            best.append((len(tgt&s)/len(tgt|s),thr,sw,sh,len(s)))
best.sort(reverse=True)
print('best alpha-threshold + downscale reproduction IoU:', [(round(v,3),t,w,h,n) for v,t,w,h,n in best[:5]])

iou,thr,sw,sh,n=best[0]
bw=a.point(lambda v: 255 if v>=thr else 0)
repro=bw.resize((sw,sh),Image.LANCZOS).resize((W,H),Image.NEAREST).point(lambda v:255 if v>=128 else 0).convert('RGB')
# visual: native alpha vs 1-bit threshold (jaggies) vs TV block
PAD=12; S=3
panels=[('A  TV screenshot: pure-white hard-edge block',A),
        ('B  channelIcon alpha (smooth, 10% semi)',a.convert('RGB')),
        ('C  alpha thresholded -> hard jaggies',bw.convert('RGB'))]
out=Image.new('RGB',(W*S*3+PAD*4,H*S+70),(22,24,28)); d=ImageDraw.Draw(out)
d.text((PAD,8),'Alpha handling: semi-transparent edge pixels are the anti-aliasing; dropping them => stair-step jaggies',fill=(255,200,120))
for i,(t,im) in enumerate(panels):
    x=PAD+i*(W*S+PAD); d.text((x,30),t,fill=(190,200,215))
    out.paste(im.resize((W*S,H*S),Image.NEAREST),(x,50))
out.save('alpha-jaggies.png'); print('wrote alpha-jaggies.png')

# ---------- 2) build the fixed okhttp cache body ----------
NAV='navfix'
orig=open(f'{NAV}/5fc2131bc283c9aa311b02961f68bdeb.1','rb').read()
txt=gzip.decompress(orig).decode('utf-8')
OLD='"channelIcon":"https://cbimg.hitv.com/prod_cms_backyard/20261105/0f9da23663f3461bb7915ddc4f90b480_5993.png"'
NEW='"channelIcon":"https://cbimg.hitv.com/prod_cms_backyard/20261105/db8667b31d874c3c9f5d728954eb96da_4398.png"'
assert txt.count(OLD)==1, 'unexpected channelIcon count %d'%txt.count(OLD)
assert len(OLD)==len(NEW)
newtxt=txt.replace(OLD,NEW)
json.loads(newtxt)   # must still be valid JSON
print('decoded len',len(txt),'->',len(newtxt),'diff bytes',sum(c1!=c2 for c1,c2 in zip(txt,newtxt)))

raw=gzip.compress(newtxt.encode('utf-8'),compresslevel=9,mtime=0)
TARGET=len(orig)
print('recompressed gzip',len(raw),'target',TARGET)
assert raw[:4]==b'\x1f\x8b\x08\x00'
# insert FEXTRA padding into gzip header so journal CLEAN 2843 stays valid
flg=0x04
head=b'\x1f\x8b\x08'+bytes([flg])+b'\x00\x00\x00\x00'+raw[8:10]
# total = 10 (header) + 2 (XLEN field) + xlen + (len(raw)-10)
xlen=TARGET-len(raw)-2
assert 0<=xlen<65536, 'cannot pad to target: %d'%xlen
fixed=head+xlen.to_bytes(2,'little')+b'\x00'*xlen+raw[10:]
assert len(fixed)==TARGET
assert gzip.decompress(fixed).decode('utf-8')==newtxt
open(f'{NAV}/fixed.1','wb').write(fixed)
print('FIX OK: bytes=%d FEXTRA pad=%d decompress OK JSON OK'%(len(fixed),xlen))
