"""Wikimedia educational images, with title, attribution, license and source."""
import hashlib,html,json,re,time
from pathlib import Path
from urllib.parse import urlencode,quote,urlsplit
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'study/illustrations'
HEADERS={'User-Agent':'LectureNotes/1.0 (local educational lecture notes)'}

def wiki(params,commons=False):
    host='commons.wikimedia.org' if commons else 'ru.wikipedia.org'
    url='https://'+host+'/w/api.php?'+urlencode(dict(action='query',format='json',formatversion=2,**params))
    with urlopen(Request(url,headers=HEADERS),timeout=8) as response:return json.load(response)

def plain(value):return html.unescape(re.sub(r'<[^>]*>','',value or ''))[:400]

def lookup(query):
    # Callers supply only an anchored public topic, never arbitrary URLs or transcript text.
    if not isinstance(query,str) or not 3<=len(query)<=70 or not re.fullmatch(r'[\w\s()«»—–-]+',query) or re.search(r'[\d@]',query):return {'status':'unavailable'}
    key=hashlib.sha256(query.casefold().encode()).hexdigest();path=CACHE/(key+'.json')
    try:
        cached=json.loads(path.read_text())
        if time.time()-cached.get('checked',0)<7*86400:return cached
    except (OSError,ValueError):pass
    pages=wiki({'generator':'search','gsrsearch':query,'gsrlimit':1,'gsrnamespace':0,'prop':'pageimages|info','inprop':'url','piprop':'thumbnail|name','pithumbsize':640}).get('query',{}).get('pages',[])
    page=pages[0] if pages else {};image=page.get('thumbnail',{}).get('source','');filename=page.get('pageimage')
    if urlsplit(image).scheme!='https' or urlsplit(image).hostname not in ('upload.wikimedia.org','thumb.wikimedia.org') or not filename:return {'status':'unavailable'}
    info=wiki({'titles':'File:'+filename,'prop':'imageinfo','iiprop':'extmetadata|url'},commons=True).get('query',{}).get('pages',[])
    details=(info[0].get('imageinfo') or [{}])[0] if info else {};meta=details.get('extmetadata',{})
    license=plain(meta.get('LicenseShortName',{}).get('value'));author=plain(meta.get('Artist',{}).get('value'))
    if not license:return {'status':'unavailable'}
    result={'status':'ready','checked':time.time(),'query':query,'title':page['title'],'image_url':image,'source_url':'https://commons.wikimedia.org/wiki/File:'+quote(filename),'article_url':page.get('fullurl'),'license':license,'author':author}
    CACHE.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False));return result
