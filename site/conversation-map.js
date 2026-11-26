"use strict";

globalThis.ZuConversation = (() => {
  const normal = s => s.toLocaleLowerCase("ru").replaceAll("ё", "е");
  const time = n => Math.floor(n / 60) + ":" + String(Math.floor(n % 60)).padStart(2, "0");
  const keyOf = n => Math.round(n * 1000);
  const cleanTime = n => typeof n === "number" && Number.isFinite(n) && n >= 0;
  const decision = /(?:^|[^а-я])(?:решили|договорились|утвердили|согласовали|принимаем решение|окончательно выбрали|решено)(?:$|[^а-я])/u;
  const acceptance = /^(?:(?:да|хорошо|итак)[, ]+)?(?:я |мы )?(?:согласен|согласна|согласны|договорились|подтверждаю|так и поступим)(?:[,.:!]|$|$)/u;
  const proposal = /^(?:давайте|предлагаю|может,?|как насчет|обсудим|предложение)(?: |,)/u;
  const actions = /(?:^|[^а-я])(?:поручаю|поручили|я (?:подготовлю|отправлю|сделаю|проверю|пришлю|беру на себя)|возьму на себя|срок сдачи)(?:$|[^а-я])/u;
  const uncertain = /(?:[«»"]|(?:^|[^а-я])(?:если|допустим|якобы|вроде|наверное|возможно|вряд ли|может быть|кажется|похоже|будто|ли|бы|уточните|спросил[аи]?|спрашивал[аи]?|(?:сказал[аи]?|говорил[аи]?|утверждал[аи]?|пишут|рассказал[аи]?),? что|напомни(?:те)?|пока думаем|под вопросом|сомневаюсь|не помн(?:ю|им|ит|ят)|не зна(?:ю|ем|ет|ют)|не уверен[аы]?|не факт|не ясно|неясно|не могу|не (?:до конца )?(?:решили|договорились|согласовали|утвердили)|не (?:приняли|подтвердили)|не (?:надо|нужно))(?=$|[^а-я]))/u;
  const cancellation = /(?:отмен(?:яем|ен[аоы]?|или|яется|ить решение)|отзыва(?:ю|ем)|больше не (?:в силе|актуальн)|(?:переносим|перенесли)|снимаем с повестки|решение утратило силу)/u;
  const labels = {pinned:"Важное", summary:"Из конспекта", decisions:"Договорённости", changes:"Отменено или изменено", actions:"Что сделать", questions:"Вопросы", explanations:"Объяснения", examples:"Примеры", review:"Проверить на слух"};
  const dateWords = [/понедельник/u,/вторник/u,/сред(?:а|у|ы|е|ой)(?=$|[^а-я])/u,/четверг/u,/пятниц/u,/суббот/u,/воскресень/u];
  const subjects = [/макет/u,/отчет/u,/экзамен/u,/встреч/u,/созвон/u,/чертеж/u,/сда(?:ть|ча|чи|ем)/u,/доклад/u,/проект/u];
  const normQuote = text => text.toLocaleLowerCase("ru").replace(/\s+/gu," ").trim();
  function terms(text, patterns) { return patterns.flatMap((ex,i)=>ex.test(text)?[i]:[]); }
  function overlaps(a,b) { return a.some(value=>b.includes(value)); }
  function classify(text) {
    const words=normal(text);
    if(text.includes("?")) return "questions";
    if(uncertain.test(words) || /(?:пока|еще|ещё) не (?:решили|определились)|отменять не|(?:не|не будем) (?:отменя|перенос)/u.test(words)) return "speech";
    if(proposal.test(words)) return "proposal";
    if(cancellation.test(words)) return "changes";
    if(decision.test(words) || acceptance.test(words)) return "decisions";
    if(actions.test(words) || /(?:домашнее задание|к следующему занятию (?:решите|подготовьте|сдайте))/u.test(words)) return "actions";
    if(/^(?:например|рассмотрим пример|приведу пример|в качестве примера)(?=$|[^а-я])/u.test(words)) return "examples";
    if(/(?:по определению|называется|называют|это означает|другими словами|обозначает)/u.test(words)) return "explanations";
    return "speech";
  }
  function prepare(segments) {
    const rows=(Array.isArray(segments)?segments:[]).flatMap(s=>{
      if(!s || !cleanTime(s.start) || !cleanTime(s.end) || s.end<=s.start) return [];
      const text=String(s.text??s.phrase??"").trim();
      if(!text) return [];
      const kind=s.needs_review && !s.reviewed ? "review" : classify(text);
      return [{start:s.start,end:s.end,text,kind,sourceId:s.id}];
    }).sort((a,b)=>a.start-b.start);
    const agreed=[];
    for(let i=0;i<rows.length;i++) {
      const row=rows[i], words=normal(row.text);
      if(row.kind==="decisions") {
        const prev=rows[i-1];
        if(prev?.kind==="proposal" && row.start-prev.end<=35 && acceptance.test(words)) {
          const a=terms(words,dateWords), b=terms(normal(prev.text),dateWords);
          if(!a.length || !b.length || overlaps(a,b)) row.references=[prev];
        }
        if(acceptance.test(words) && !row.references && row.text.split(/\s+/).length<3) row.kind="speech";
        else agreed.push(row);
      } else if(row.kind==="changes") {
        const dates=terms(words,dateWords), scope=terms(words,subjects);
        const candidates=agreed.filter(prior=>{
          if(prior.kind!=="decisions") return false;
          const previous=normal([prior.text,...(prior.references || []).map(r=>r.text)].join(" "));
          const oldScope=terms(previous,subjects);
          if(scope.length && oldScope.length && !overlaps(scope,oldScope)) return false;
          return (dates.length && overlaps(dates,terms(previous,dateWords))) || (scope.length && overlaps(scope,oldScope));
        });
        if(candidates.length===1) {
          candidates[0].kind="superseded"; row.references=[candidates[0]];
        } else if(candidates.length>1 || (!dates.length && !scope.length)) {
          const possible=candidates.length?candidates:agreed.filter(x=>x.kind==="decisions" && row.start-x.end<=25).slice(-1);
          for(const prior of possible){prior.kind="review";prior.reason="После этой фразы прозвучала поправка. Нужно сверить, к чему она относится.";}
        }
      }
    }
    return rows;
  }

  function topicGroups(rows) { return ZuMind.groups(rows); }
  const views=new WeakMap();

  function stored(key) {
    try {
      const list=JSON.parse(localStorage.getItem("zu-map:pins:"+key) || "[]");
      return Array.isArray(list) ? list.filter(cleanTime) : [];
    } catch { return []; }
  }

  function element(tag,cls,value) {
    const node=document.createElement(tag);
    if(cls) node.className=cls;
    if(value!==undefined) node.textContent=value;
    return node;
  }

  function mount(host, data) {
    const rows=prepare(data.segments);
    const previous=views.get(host);
    previous?.graph?.dispose();
    const view=previous?.key===data.key ? previous : {key:data.key, graph:null, zoom:{}};
    views.set(host,view);
    const pins=new Set((data.pins ?? stored(data.key)).filter(cleanTime).map(keyOf));
    let latestEnd=0;
    const prefixEnd=rows.map(row=>latestEnd=Math.max(latestEnd,row.end));
    const marks=(data.marks || []).filter(m=>m && cleanTime(m.time));
    const open=view.open ??= new Set(["pinned","summary","decisions","actions","questions","topic-0"]);
    const limits=view.limits ??= new Map();
    const topics=topicGroups(rows);
    const byKind=new Map();
    for (const row of rows) {
      if(!byKind.has(row.kind)) byKind.set(row.kind,[]);
      byKind.get(row.kind).push(row);
    }
    const timed=new Map();
    for(const row of rows) {
      if(!timed.has(row.start)) timed.set(row.start,[]);
      timed.get(row.start).push(row);
    }
    const cited=new Set();
    const unresolved=[];
    for(const citation of data.evidence || []) {
      if(!citation || typeof citation.quote!=="string") continue;
      let match;
      if(citation.source_status==="confirmed") {
        const starts=timed.get(citation.start) || [];
        for(const first of starts) {
          if(first.kind==="review" || (first.sourceId!==undefined && citation.segment_id!==first.sourceId)) continue;
          const span=[first]; let last=first, index=rows.indexOf(first);
          while(last.end<citation.end && index+1<rows.length) {
            const next=rows[++index],gap=next.start-last.end;
            if(gap<-.25 || gap>2 || next.kind==="review") break;
            span.push(next);last=next;
          }
          if(last.end===citation.end && normQuote(span.map(r=>r.text).join(" "))===normQuote(citation.quote)) {
            match=span.length===1?first:{...first,end:last.end,text:citation.quote,references:span}; break;
          }
        }
      }
      if(match) cited.add(match);
      else {
        const anchor=citation.original_source || citation;
        if(cleanTime(anchor.start) && cleanTime(anchor.end) && anchor.end>anchor.start) {
          unresolved.push({start:anchor.start,end:anchor.end,text:String(anchor.quote || citation.quote),kind:"review",reason:"Прежняя цитата. Сверь с оригиналом."});
        }
      }
    }
    const title=String(data.title || "Разговор");
    let branches=[];
    function selectedRows() {
      const moments=new Map(marks.map(mark=>[keyOf(mark.time),mark.name || "Закладка"]));
      for (const mark of pins) if(!moments.has(mark)) moments.set(mark,"Отмеченный момент");
      const entries=[];
      let index=0;
      for (const [ms,label] of [...moments].sort((a,b)=>a[0]-b[0])) {
        const t=ms/1000;
        while(index+1<rows.length && rows[index+1].start<=t) index++;
        let source;
        for(let j=rows.length?index:-1;j>=0;j--) {
          if(rows[j].start<=t && rows[j].end>t){source=rows[j];break;}
          if(j===0 || prefixEnd[j-1]<=t) break;
        }
        entries.push({start:t,end:source?.end ?? t,text:source?.text || label,kind:source?.kind || "mark",note:source && label!=="Отмеченный момент" ? label : ""});
      }
      return entries;
    }
    function makeBranches() {
      const groups=[];
      const pinned=selectedRows();
      if(pinned.length) groups.push({id:"pinned",title:labels.pinned,rows:pinned});
      if(cited.size) groups.push({id:"summary",title:labels.summary,rows:[...cited]});
      for(const kind of ["decisions","changes","actions","questions","explanations","examples","review"]) {
        const base=byKind.get(kind) || [];
        const found=kind==="review" ? base.concat(unresolved) : base;
        if(found?.length) groups.push({id:kind,title:labels[kind],rows:found});
      }
      if(topics.length) groups.push(...topics);
      return groups;
    }
    function toggle(t) {
      const ms=keyOf(t), yes=!pins.has(ms);
      if(yes) { pins.add(ms); open.add("pinned"); } else pins.delete(ms);
      if(data.onPin) data.onPin(ms/1000,yes);
      else try { localStorage.setItem("zu-map:pins:"+data.key,JSON.stringify([...pins].map(n=>n/1000))); } catch {}
    }
    function leaf(row,group) {
      const li=element("li","zu-map-leaf");
      const tap=element("button","zu-map-listen");tap.type="button";
      tap.disabled=data.canPlay===false;
      tap.setAttribute("aria-label","Слушать с "+time(row.start)+". "+row.text);
      const when=element("span","zu-map-time",time(row.start));
      if(row.kind==="review") when.append(element("small","zu-map-warn","Проверить на слух"));
      tap.append(when,element("span","zu-map-quote",row.text));
      if(row.reason) tap.append(element("small","zu-map-note",row.reason));
      if(row.note) tap.append(element("small","zu-map-note",row.note));
      tap.onclick=()=>data.play(row.start);
      const star=element("button","zu-map-pin");
      star.type="button";star.dataset.ms=keyOf(row.start);
      star.setAttribute("aria-pressed",String(pins.has(keyOf(row.start))));
      star.setAttribute("aria-label",(pins.has(keyOf(row.start))?"Убрать из важного":"Отметить как важное")+" · "+time(row.start));
      star.title=star.getAttribute("aria-label");
      star.append(element("span",null,pins.has(keyOf(row.start))?"★":"☆"));
      star.onclick=()=>{
        toggle(row.start);render();
        const active=host.querySelector('[data-group="'+group.id+'"] .zu-map-pin[data-ms="'+keyOf(row.start)+'"]') || host.querySelector('.zu-map-pin[data-ms="'+keyOf(row.start)+'"]') || host.querySelector("summary");
        active?.focus({preventScroll:true});
      };
      li.append(tap,star);
      if(row.references?.length) {
        const source=element("details","zu-map-references"),summary=element("summary",null,"Связанные реплики · "+row.references.length);source.append(summary);
        for(const ref of row.references) {
          const link=element("button","zu-map-listen",time(ref.start)+"  "+ref.text);link.type="button";link.disabled=data.canPlay===false;
          link.onclick=()=>data.play(ref.start);source.append(link);
        }
        li.append(source);
      }
      return li;
    }
    function branch(group) {
      const details=element("details","zu-map-branch");details.dataset.group=group.id;details.open=open.has(group.id);
      const heading=element("summary","zu-map-heading");
      const category=group.id.startsWith("topic-")? "Тема · "+time(group.start) : "";
      const name=element("span","zu-map-name");
      if(category) name.append(element("small","zu-map-kicker",category));
      name.append(element("strong",null,group.title));
      heading.append(name,element("span","zu-map-number",String(group.rows.length)));details.append(heading);
      function fill(){
        const list=element("ul","zu-map-leaves");
        const limit=limits.get(group.id) || 3;
        for(const row of group.rows.slice(0,limit)) list.append(leaf(row,group));
        const more=element("button","zu-map-more","Ещё фразы · "+(group.rows.length-limit));
        more.type="button";
        if(limit<group.rows.length) {
          more.onclick=()=>{
            limits.set(group.id,limit+16);list.remove();more.remove();fill();
            details.querySelectorAll(".zu-map-listen")[limit]?.focus({preventScroll:true});
          };
          details.append(list,more);
        } else details.append(list);
      }
      if(details.open) fill();
      details.ontoggle=()=>{
        if(details.open) {open.add(group.id);if(!details.querySelector("ul"))fill();}
        else open.delete(group.id);
      };
      return details;
    }
    function render(){
      branches=makeBranches();
      host.replaceChildren();host.classList.add("zu-map");
      if(!branches.length){host.append(element("p","zu-map-empty",data.empty || "Карта появится после расшифровки. Сначала можно отметить важный момент во время прослушивания."));return;}
      view.graph?.dispose();
      const top=element("div","zu-map-root");
      top.append(element("span","zu-map-kicker","Карта разговора"),element("strong",null,title));
      const tree=element("div","zu-map-tree");
      for(const g of branches) tree.append(branch(g));
      if(topics.length) {
        view.graph=ZuMind.graphical(title,topics,id=>{
          const details=tree.querySelector('[data-group="'+id+'"]');
          if(details){details.open=true;details.querySelector("summary").focus();details.scrollIntoView({block:"nearest"});}
        },data.play,view.zoom,data.canPlay!==false);
        host.append(view.graph);
      }
      host.append(top,tree);
      const tools=element("div","zu-map-tools");
      const copy=element("button","zu-map-more","Скопировать краткую карту");
      copy.type="button";
      const notice=element("span","zu-map-note");
      notice.setAttribute("role","status");
      function outlineMarkdown(compact) {
        const plain=value=>String(value).replace(/[\r\n]+/gu," ").replace(/([\\*_`<>~|\[\]])/gu,"\\$1");
        const lines=["# "+plain(title)];
        for(const group of branches) {
          lines.push("","## "+plain(group.title));
          const entries=compact && group.id.startsWith("topic-")?group.rows.slice(0,3):group.rows;
          for(const row of entries) {
            lines.push("- "+time(row.start)+"  "+plain(row.text));
            if(row.reason || row.note) lines.push("  - "+plain(row.reason || row.note));
            for(const source of row.references || []) lines.push("  - "+time(source.start)+"  "+plain(source.text));
          }
        }
        return lines.join("\n");
      }
      copy.onclick=async()=>{
        const outline=outlineMarkdown(true);
        try { await navigator.clipboard.writeText(outline); notice.textContent="Карта скопирована"; }
        catch {
          const field=tools.querySelector("textarea") || element("textarea","zu-map-export");
          field.readOnly=true;field.setAttribute("aria-label","Текст карты для копирования");
          field.value=outline;tools.append(field);field.focus();field.select();
          notice.textContent="Текст выделен для копирования.";
        }
      };
      const full=()=>ZuMind.outline(title,topics,branches.filter(g=>g.id==="pinned" || g.id==="summary" || g.id==="review" && unresolved.length),data.key);
      function sendFile(name,mime,bytes) {
        if(data.onFile){data.onFile(name,mime,bytes);return;}
        const link=element("a"),url=URL.createObjectURL(new Blob([bytes],{type:mime}));
        link.href=url;link.download=name;tools.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
      }
      const filename=(title.replace(/[\\/:*?"<>|]/gu," ").slice(0,90) || "зу")+" — карта";
      const xmind=element("button","zu-map-more","Сохранить для XMind");xmind.type="button";
      xmind.onclick=()=>{try{sendFile(filename+".xmind","application/vnd.xmind.workbook",ZuMind.archive(full()));}catch{notice.textContent="Файл карты не создался. Попробуй ещё раз.";}};
      const download=element("button","zu-map-more","Сохранить Markdown");download.type="button";
      download.onclick=()=>{
        const lines=[];
        function append(node, level) {
          const text=node.title.replace(/[\r\n]+/gu," ").replace(/([\\*_`<>~|\[\]])/gu,"\\$1");
          if(level===0) lines.push("# "+text);
          else if(level===1) lines.push("","## "+text);
          else if(level===2 && !node.kind) lines.push("","### "+text);
          else lines.push("  ".repeat(Math.max(0,level-3))+"- "+(Number.isFinite(node.start)?time(node.start)+"  ":"")+text+(node.note?" ("+node.note+")":""));
          for(const child of node.children || []) append(child,level+1);
        }
        append(full(),0);
        const content=lines.join("\n");
        sendFile(filename+".md","text/markdown",new TextEncoder().encode(content));
      };
      tools.append(xmind,download,copy,notice);host.append(tools);
    }
    render();
  }
  return {mount,prepare,topicGroups};
})();
