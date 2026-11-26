"use strict";

globalThis.ZuLibraryStorage = (() => {
  const constants = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
  ]);
  const rotate = (word, count) => (word >>> count) | (word << (32-count));
  class Sha256 {
    constructor() {
      this.h = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
      this.words = new Uint32Array(64);
      this.tail = new Uint8Array(64);
      this.used = 0;
      this.length = 0;
    }
    block(view, offset) {
      const w = this.words;
      for (let i=0;i<16;i++) w[i]=view.getUint32(offset+4*i);
      for (let i=16;i<64;i++) {
        const a=w[i-15], b=w[i-2];
        w[i]=w[i-16]+(rotate(a,7)^rotate(a,18)^(a>>>3))+w[i-7]+(rotate(b,17)^rotate(b,19)^(b>>>10));
      }
      let [a,b,c,d,e,f,g,h]=this.h;
      for (let i=0;i<64;i++) {
        const t=h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+constants[i]+w[i];
        const m=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));
        h=g; g=f; f=e; e=(d+t)>>>0; d=c; c=b; b=a; a=(t+m)>>>0;
      }
      const s=this.h;
      s[0]+=a; s[1]+=b; s[2]+=c; s[3]+=d; s[4]+=e; s[5]+=f; s[6]+=g; s[7]+=h;
    }
    update(bytes) {
      this.length+=bytes.length;
      let n=0;
      if(this.used) {
        n=Math.min(64-this.used,bytes.length);
        this.tail.set(bytes.subarray(0,n),this.used); this.used+=n;
        if(this.used<64) return;
        this.block(new DataView(this.tail.buffer),0); this.used=0;
      }
      const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
      for(;n+64<=bytes.length;n+=64) this.block(view,n);
      if(n<bytes.length) { this.tail.set(bytes.subarray(n)); this.used=bytes.length-n; }
    }
    finish() {
      const bytes=new Uint8Array(this.used<56?64:128);
      bytes.set(this.tail.subarray(0,this.used)); bytes[this.used]=128;
      const view=new DataView(bytes.buffer);
      view.setUint32(bytes.length-8,Math.floor(this.length/0x20000000));
      view.setUint32(bytes.length-4,(this.length*8)>>>0);
      for(let i=0;i<bytes.length;i+=64) this.block(view,i);
      return Array.from(this.h,n=>n.toString(16).padStart(8,"0")).join("");
    }
  }
  async function hashFile(file, progress=()=>{}, background=false) {
    const hash=new Sha256();
    const step=background ? 1024*1024 : 64*1024;
    let last=0, sliceStart=performance.now();
    for(let offset=0;offset<file.size;offset+=step) {
      const bytes=new Uint8Array(await file.slice(offset,offset+step).arrayBuffer());
      hash.update(bytes);
      const now=performance.now();
      if(now-last>=160) { progress(Math.floor(100*(offset+bytes.length)/file.size)); last=now; }
      if(!background && now-sliceStart>=6) {
        await new Promise(resolve=>setTimeout(resolve,0));
        sliceStart=performance.now();
      }
    }
    return hash.finish();
  }
  if(typeof document==="undefined" && typeof WorkerGlobalScope!=="undefined" && self instanceof WorkerGlobalScope) {
    self.onmessage=async event=>{
      try { self.postMessage({digest:await hashFile(event.data,percent=>self.postMessage({percent}),true)}); }
      catch { self.postMessage({failed:true}); }
    };
  }
  const workerURL=typeof document!=="undefined" ? document.currentScript?.src : null;
  async function identify(file, progress=()=>{}) {
    if(workerURL && typeof Worker==="function") {
      let worker;
      try {
        worker=new Worker(workerURL);
        return await new Promise((resolve,reject)=>{
          worker.onmessage=({data})=>{
            if(data.digest) resolve(data.digest);
            else if(data.failed) reject(Error("read"));
            else progress(data.percent);
          };
          worker.onerror=event=>{event.preventDefault();reject(Error("worker"));};
          worker.postMessage(file);
        });
      } catch {} finally { worker?.terminate(); }
    }
    return hashFile(file,progress);
  }

  const format="zu.library.notes", version=1, validId=s=>typeof s==="string" && /^[0-9a-f]{64}$/.test(s);
  const timeOK=n=>Number.isFinite(n) && n>=0 && n<=Number.MAX_SAFE_INTEGER/1000;
  const milliseconds=n=>Math.round(n*1000)/1000;
  const token=()=>globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+"-"+Math.random().toString(36).slice(2);
  const empty=()=>({time:0,favorite:false,cues:[],marks:[],pins:[],notes:[]});
  const snapshot=s=>({time:s.time,favorite:s.favorite,cues:s.cues,marks:s.marks,pins:s.pins,notes:s.notes});
  function invalid(){throw Error("Формат файла заметок повреждён или содержит недопустимые значения.");}
  function times(list) {
    if(!Array.isArray(list) || list.length>100000 || !list.every(timeOK)) invalid();
    return [...new Set(list.map(milliseconds))].sort((a,b)=>a-b);
  }
  function limits(cues,notes) {
    if(cues.length>70000 || notes.length>10000 ||
       cues.reduce((sum,cue)=>sum+cue.phrase.length,0)>8500000 ||
       notes.reduce((sum,note)=>sum+note.text.length,0)>4000000) {
      throw Error("Объём текста и заметок превышает предел одной записи. Сохрани свои файлы отдельно.");
    }
  }
  function readWork(raw) {
    if(!raw || !timeOK(raw.time) || typeof raw.favorite!=="boolean" || !Array.isArray(raw.cues) || raw.cues.length>70000 ||
        !Array.isArray(raw.notes) || raw.notes.length>10000) invalid();
    const uniqueCues=new Set();
    const cues=raw.cues.map(c=>{
      if(!c || !timeOK(c.start) || !timeOK(c.end) || c.end<=c.start || typeof c.phrase!=="string" ||
         !c.phrase.trim() || c.phrase.length>32768) invalid();
      return {start:c.start,end:c.end,phrase:c.phrase.trim()};
    }).filter(cue=>{
      const identity=JSON.stringify([cue.start,cue.end,cue.phrase]);
      if(uniqueCues.has(identity)) return false;
      uniqueCues.add(identity);return true;
    }).sort((a,b)=>a.start-b.start);
    const notes=raw.notes.map(n=>{
      if(!n || typeof n.id!=="string" || !n.id || n.id.length>200 || !timeOK(n.time) || typeof n.text!=="string" ||
         !n.text.trim() || n.text.length>3000) invalid();
      return {id:n.id,time:milliseconds(n.time),text:n.text.trim()};
    });
    limits(cues,notes);
    return {time:milliseconds(raw.time),favorite:raw.favorite,cues,marks:times(raw.marks),pins:times(raw.pins),notes};
  }
  function backup(id,file,work) {
    return {format,version,audio:{sha256:id,bytes:file.size,name:file.name},work:snapshot(work)};
  }
  function unpack(raw) {
    if(!raw || raw.format!==format) throw Error("Это файл другого формата. Выбери JSON заметок «зу».");
    if(raw.version!==version) throw Error("Эта версия файла заметок пока не поддерживается.");
    if(!raw.audio || (raw.audio.sha256!==null && !validId(raw.audio.sha256)) || typeof raw.audio.name!=="string" || raw.audio.name.length>4096 || !Number.isSafeInteger(raw.audio.bytes) || raw.audio.bytes<0) invalid();
    return {id:raw.audio.sha256,size:raw.audio.bytes,name:raw.audio.name,work:readWork(raw.work)};
  }
  function combine(target,incoming,allowTime) {
    const s=snapshot(target);
    combineWork(s,incoming,allowTime);
    limits(s.cues,s.notes);
    Object.assign(target,s);
  }
  function combineWork(s,incoming,allowTime) {
    if(allowTime) s.time=incoming.time;
    s.favorite ||= incoming.favorite;
    s.marks=times([...new Set([...s.marks,...incoming.marks])]);
    s.pins=times([...new Set([...s.pins,...incoming.pins])]);
    const signature=n=>JSON.stringify([n.time,n.text]);
    const known=new Set(s.notes.map(signature)), ids=new Set(s.notes.map(x=>x.id));
    const addedNotes=[];
    for(const incomingNote of incoming.notes) {
      const sig=signature(incomingNote);
      if(known.has(sig)) continue;
      const note={...incomingNote};
      if(ids.has(note.id)) note.id=token();
      known.add(sig); ids.add(note.id); addedNotes.push(note);
    }
    if(addedNotes.length) s.notes=s.notes.concat(addedNotes);
    if(!s.cues.length) { s.cues=incoming.cues; return; }
    if(!incoming.cues.length) return;
    const additions=[];
    let cursor=0, latestEnd=0;
    for(const cue of incoming.cues) {
      while(cursor<s.cues.length && s.cues[cursor].start<cue.end && s.cues[cursor].start<=cue.start) {
        latestEnd=Math.max(latestEnd,s.cues[cursor++].end);
      }
      if(latestEnd<=cue.start && (cursor===s.cues.length || s.cues[cursor].start>=cue.end)) additions.push(cue);
    }
    if(additions.length) s.cues=s.cues.concat(additions).sort((a,b)=>a.start-b.start);
  }
  function apply(s,action) {
    switch(action.kind) {
      case "time": s.time=action.value; break;
      case "favorite": s.favorite=action.value; break;
      case "cues": s.cues=action.value; break;
      case "marks": case "pins": {
        const set=new Set(s[action.kind]); const time=milliseconds(action.time);
        if(action.add) set.add(time); else set.delete(time);
        if(set.size>100000) throw Error("Достигнут предел отметок для одной записи.");
        s[action.kind]=[...set].sort((a,b)=>a-b); break;
      }
      case "note": {
        const existing=s.notes.find(n=>n.id===action.id);
        const changedElsewhere=action.before && existing && (existing.time!==action.before.time || existing.text!==action.before.text);
        if(changedElsewhere && (!action.value || s.notes.some(n=>n.time===action.value.time && n.text===action.value.text))) break;
        const notes=changedElsewhere ? [...s.notes,{...action.value,id:action.conflictId}] : s.notes.filter(n=>n.id!==action.id);
        if(!changedElsewhere && action.value) notes.push(action.value);
        limits([],notes);s.notes=notes;break;
      }
      case "merge": combine(s,action.value,action.allowTime); break;
      default: throw Error("Неизвестное изменение заметок.");
    }
    return s;
  }

  let handle;
  function database() {
    if(handle) return handle;
    handle=new Promise((resolve,reject)=>{
      const request=indexedDB.open("zu-library-work",1);
      request.onupgradeneeded=()=>{
        const store=request.result.createObjectStore("records",{keyPath:"id"});
        store.createIndex("name","name");
        request.result.createObjectStore("positions",{keyPath:"id"});
      };
      request.onerror=()=>reject(request.error);
      request.onblocked=()=>reject(Error("blocked"));
      request.onsuccess=()=>{
        const db=request.result;
        db.onversionchange=()=>{db.close();handle=null;};
        resolve(db);
      };
    }).catch(err=>{handle=null;throw err;});
    return handle;
  }
  async function transaction(stores,mode,run) {
    const db=await database();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction(stores,mode);
      let result, reason;
      const watch=(request,callback)=>{
        request.onsuccess=()=>{
          try { callback(request.result); } catch(e) {reason=e;tx.abort();}
        };
      };
      tx.oncomplete=()=>resolve(result);
      tx.onabort=()=>reject(reason || tx.error || Error("blocked"));
      try {run(tx,watch,value=>{result=value;});} catch(e) {reason=e;tx.abort();}
    });
  }
  const journalKey=id=>"zu-library:v1:time:"+id;
  function journal(row) {
    try {
      const key=journalKey(row.id),current=JSON.parse(localStorage.getItem(key));
      if(current?.epoch===row.epoch && current.at>row.at) return;
      localStorage.setItem(key,JSON.stringify(row));
    } catch {}
  }
  async function read(id) {
    let row, point;
    await transaction(["records","positions"],"readonly",(tx,watch)=>{
      watch(tx.objectStore("records").get(id),r=>{row=r;});
      watch(tx.objectStore("positions").get(id),r=>{point=r;});
    });
    if(!row) return null;
    try {
      const last=JSON.parse(localStorage.getItem(journalKey(id)));
      if(last && last.epoch===row.epoch && timeOK(last.time) && Number.isFinite(last.at) && (!point || last.at>=point.at)) point=last;
    } catch {}
    row.work=readWork(row.work);
    if(point?.epoch===row.epoch && timeOK(point.time)) row.work.time=point.time;
    return row;
  }
  const point=(id,epoch,time)=>({id,epoch,time,at:Date.now()});
  function save(id,file,work,retries=[]) {
    return transaction(["records","positions"],"readwrite",(tx,watch,done)=>{
      const records=tx.objectStore("records");
      watch(records.get(id),previous=>{
        const row=previous || {id,epoch:token(),name:file.name,size:file.size,work:empty()};
        combine(row.work,work,false);
        for(const action of retries) apply(row.work,action);
        row.work.time=work.time;
        records.put(row);
        tx.objectStore("positions").put(point(id,row.epoch,work.time));
        done(row);
      });
    });
  }
  function update(id,epoch,action) {
    if(action.kind==="time") {
      const changed=point(id,epoch,action.value);
      return transaction(["positions"],"readwrite",(tx,watch)=>{
        const positions=tx.objectStore("positions");
        watch(positions.get(id),old=>{
          if(old?.epoch!==epoch) throw Error("removed");
          if(old.at<=changed.at) positions.put(changed);
        });
      }).then(()=>{journal(changed);});
    }
    return transaction(["records","positions"],"readwrite",(tx,watch)=>{
      const records=tx.objectStore("records");
      watch(records.get(id),row=>{
        if(row?.epoch!==epoch) throw Error("removed");
        apply(row.work,action); records.put(row);
        if(action.kind==="merge" && action.allowTime) tx.objectStore("positions").put(point(id,epoch,action.value.time));
      });
    });
  }
  async function remove(id) {
    await transaction(["records","positions"],"readwrite",tx=>{tx.objectStore("records").delete(id);tx.objectStore("positions").delete(id);});
    try {localStorage.removeItem(journalKey(id));}catch{}
  }
  function list() {
    return transaction(["records"],"readonly",(tx,watch,done)=>{
      const rows=[];
      watch(tx.objectStore("records").index("name").openKeyCursor(),cursor=>{
        if(cursor){rows.push({id:cursor.primaryKey,name:cursor.key});cursor.continue();}
        else done(rows);
      });
    });
  }
  return {identify,hashFile,empty,snapshot,backup,unpack,readWork,apply,combine,token,milliseconds,read,save,update,remove,list,point,journal};
})();
