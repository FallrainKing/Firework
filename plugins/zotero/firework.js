/* Firework manual exchange. No direct Zotero database or model access. */
var FireworkPlugin = {
  id:null,menus:[],busy:false,queue:[],exports:{},
  pref(k){return Zotero.Prefs.get('extensions.firework.'+k,true)},
  set(k,v){Zotero.Prefs.set('extensions.firework.'+k,v,true)},
  win(){return Zotero.getMainWindow()},
  notice(s){Services.prompt.alert(this.win(),'Firework',s)},
  async start(id,rootURI){
    this.id=id;this.rootURI=rootURI;
    this.path=PathUtils.join(Zotero.DataDirectory.dir,'firework-sync.json');
    if(await IOUtils.exists(this.path)){const saved=JSON.parse(await IOUtils.readUTF8(this.path));if(!Array.isArray(saved.queue)||!saved.exports||typeof saved.exports!=='object')throw new Error('同步记录损坏。请先备份 firework-sync.json 后联系维护者恢复；未启动同步。');this.queue=saved.queue;this.exports=saved.exports;for(const job of this.queue)if(job.status==='sending'){job.status='failed';job.error='上次传输中断；文件可能已保存，请手动重试（不会重复创建已有内容）'}}
    const entries=[['pair','配对 / 连接 Firework',()=>this.pair()],['selected','发送所选论文到 Firework',()=>this.sendSelected()],['collection','发送当前分类到 Firework',()=>this.sendCollection()],['retry','重试待发送论文',()=>this.drain()],['receive','接收 Firework 待同步论文',()=>this.receive()],['status','查看同步状态',()=>this.status()]];
    for(const [key,label,fn] of entries){
      const menuID=Zotero.MenuManager.registerMenu({menuID:'firework-'+key,pluginID:id,target:'main/menubar/tools',menus:[{menuType:'menuitem',onShowing:(_e,c)=>c.menuElem.setAttribute('label','Firework · '+label),onCommand:()=>this.run(fn)}]});
      this.menus.push(menuID);
    }
    this.menus.push(Zotero.MenuManager.registerMenu({menuID:'firework-context',pluginID:id,target:'main/library/item',menus:[{menuType:'menuitem',onShowing:(_e,c)=>{c.menuElem.setAttribute('label','发送到 Firework');c.setVisible(c.items?.some(i=>i.isRegularItem()))},onCommand:()=>this.run(()=>this.sendSelected())}]}));
  },
  stop(){for(const id of this.menus)if(id)Zotero.MenuManager.unregisterMenu(id);this.menus=[]},
  async save(){const temp=this.path+'.tmp';await IOUtils.writeUTF8(temp,JSON.stringify({queue:this.queue,exports:this.exports}),{mode:'overwrite'});await IOUtils.setPermissions(temp,0o600);await IOUtils.move(temp,this.path,{noOverwrite:false})},
  async run(fn){if(this.busy)return this.notice('已有同步操作执行中。');this.busy=true;try{await fn()}catch(e){this.notice(e.message||'同步失败；未覆盖另一端资料。')}finally{this.busy=false}},
  origin(){const value=this.pref('origin')||'https://paper.matchesai.vip';const url=new (this.win().URL)(value);if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error('请输入 HTTPS 站点地址，不带路径、账号或查询参数。');return url.origin},
  async credential(){const origin=this.origin(),device=this.pref('device');const rows=await Services.logins.findLogins(origin,null,'Firework Zotero');return rows.find(r=>r.username===device)?.password},
  async storeCredential(origin,device,token){const {nsLoginInfo}=ChromeUtils.importESModule('resource://gre/modules/LoginInfo.sys.mjs');const rows=await Services.logins.findLogins(origin,null,'Firework Zotero');for(const r of rows)if(r.username===device)await Services.logins.removeLogin(r);const login=new nsLoginInfo();login.init(origin,null,'Firework Zotero',device,token,'','');await Services.logins.addLoginAsync(login);this.set('device',device)},
  async request(path,body=undefined,options={}){
    const headers={...options.headers};if(!options.public){const token=await this.credential();if(!token)throw new Error('请先在工具菜单中配对 Firework。');headers.Authorization='Bearer '+token}
    let payload=body;
    if(body!==undefined&&!options.form){payload=JSON.stringify(body);headers['Content-Type']='application/json'}
    if(options.form)headers['Content-Type']='multipart/form-data';
    const r=await Zotero.HTTP.request(options.method||(body===undefined?'GET':'POST'),this.origin()+path,{body:payload,headers,responseType:options.binary?'arraybuffer':'json',successCodes:false,followRedirects:false,timeout:options.timeout||180000,logBodyLength:0});
    if(r.status<200||r.status>=300){const detail=options.binary?null:r.response?.detail;throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?'字段校验失败：'+detail.map(e=>(e.loc||[]).join('.')+' '+e.msg).join('；'):`同步请求失败（${r.status}）`)}
    return r.response;
  },
  async pair(){
    const input={value:this.pref('origin')||'https://paper.matchesai.vip'};
    if(!Services.prompt.prompt(this.win(),'Firework 配对','Firework HTTPS 地址：',input,null,{}))return;
    const old=this.pref('origin');this.set('origin',input.value.trim());
    try{this.origin()}catch(e){if(old)this.set('origin',old);else Zotero.Prefs.clear('extensions.firework.origin',true);throw e}
    let instance=this.pref('instance');if(!instance){instance=Zotero.Utilities.randomString(32);this.set('instance',instance)}
    const name='Zotero '+Zotero.version+' · '+(Services.appinfo.OS||'desktop');
    const p=await this.request('/api/zotero/pair/start',{name,instance_id:instance},{public:true});
    Zotero.launchURL(p.verification_url);
    this.notice('请在 Firework 的 Zotero 集成页输入配对码：\n\n'+p.user_code+'\n\n确认设备授权后关闭此提示，插件将领取凭据。配对码 10 分钟有效。');
    const end=Date.now()+p.expires_in*1000;
    while(Date.now()<end){const r=await this.request('/api/zotero/pair/claim',{pair_id:p.pair_id,device_code:p.device_code},{public:true});if(r.status==='approved'){await this.storeCredential(this.origin(),r.device_id,r.token);this.notice('配对成功。可手动发送论文，或接收 Firework 待同步任务。凭据可在网页撤销，30 天后需重新配对。');return}await Zotero.Promise.delay(2500)}
    throw new Error('配对已超时，请重试。');
  },
  arxiv(item){const text=(item.getField('url')||'')+'\n'+(item.getField('extra')||'');return text.match(/(?:arxiv\.org\/(?:abs|pdf)\/|arxiv:\s*)((?:\d{4}\.\d{4,5}|[a-zA-Z.-]+\/\d{7})(?:v\d+)?)/i)?.[1]||''},
  async categoryPaths(item){const out=[];for(const id of item.getCollections()){let c=Zotero.Collections.get(id),path=[],seen=new Set();while(c&&!seen.has(c.id)){seen.add(c.id);path.unshift(c.name);c=c.parentID?Zotero.Collections.get(c.parentID):null}if(path.length)out.push(path)}return out},
  async enqueueItems(items){
    if(!await this.credential())throw new Error('请先配对 Firework。');
    const parents=items.map(i=>i.isRegularItem()?i:i.parentItemID?Zotero.Items.get(i.parentItemID):null);
    const valid=[...new Map(parents.filter(i=>i?.isRegularItem()&&!i.deleted).map(i=>[i.id,i])).values()];if(!valid.length)throw new Error('请选择文献条目，而不是单独的附件或笔记。');
    if(!Services.prompt.confirm(this.win(),'发送到 Firework',`将发送 ${valid.length} 个条目的书目信息、分类、标签和本地 PDF。不会调用研究模型，缺失附件将提示重试。继续？`))return;
    const queued=[];
    for(const item of valid){const creators=item.getCreators();const job={id:Zotero.Utilities.randomString(24),origin:this.origin(),device:this.pref('device'),status:'pending',itemID:item.id,
      body:{library_key:String(item.libraryID),item_key:item.key,title:item.getField('title')||'Untitled',authors:creators.map(c=>[c.firstName,c.lastName].filter(Boolean).join(' ')),abstract:item.getField('abstractNote')||'',doi:item.getField('DOI')||'',arxiv_id:this.arxiv(item),url:item.getField('url')||'',tags:item.getTags().map(t=>t.tag),collection_paths:await this.categoryPaths(item),raw:item.toJSON()},attachments:[],error:''};
      const best=await item.getBestAttachment();for(const id of item.getAttachments()){const a=Zotero.Items.get(id);if(a.attachmentContentType==='application/pdf')job.attachments.push({id,key:a.key,label:(a.getField('title')||'PDF').slice(0,100),role:best?.id===id?'main':'supplement'})}
      if(job.attachments.length&&!job.attachments.some(a=>a.role==='main'))job.attachments[0].role='main';
      job.attachments.sort((a,b)=>(a.role==='main'?0:1)-(b.role==='main'?0:1));
      const previous=this.queue.find(j=>j.status!=='completed'&&j.origin===job.origin&&j.device===job.device&&j.body.library_key===job.body.library_key&&j.body.item_key===job.body.item_key);
      if(previous){Object.assign(previous,{body:job.body,attachments:job.attachments,status:'pending',error:''});queued.push(previous.id)}else{this.queue.push(job);queued.push(job.id)}
    }
    await this.save();await this.drain(queued);
  },
  async sendSelected(){await this.enqueueItems(Zotero.getActiveZoteroPane().getSelectedItems())},
  async sendCollection(){const c=Zotero.getActiveZoteroPane().getSelectedCollection();if(!c)throw new Error('请先选中一个分类。');const ids=new Set();const visit=async col=>{for(const i of await col.getChildItems())if(i.isRegularItem())ids.add(i.id);for(const child of col.getChildCollections())await visit(child)};await visit(c);await this.enqueueItems([...ids].map(id=>Zotero.Items.get(id)))},
  async drain(ids=null){
    let ok=0,failed=0;
    for(const job of this.queue.filter(j=>j.status!=='completed'&&(!ids||ids.includes(j.id)))){
      if(job.origin!==this.origin()||job.device!==this.pref('device')){job.error='原连接已变化，请在原账号连接下处理或重新选择发送。';failed++;continue}
      job.status='sending';await this.save();
      try{const main=job.attachments.find(a=>a.role==='main');if(main){const a=Zotero.Items.get(main.id);const path=a&&await a.getFilePathAsync();if(path&&await IOUtils.exists(path)&&(await IOUtils.stat(path)).size<=50*1024*1024)job.body.pdf_hash=await this.hash(await IOUtils.read(path))}
        const r=await this.request('/api/zotero/device/items',job.body);job.paperId=r.paper_id;await this.save();
        for(const info of job.attachments){const a=Zotero.Items.get(info.id);if(!a||a.key!==info.key)throw new Error('本地附件已删除或变化。');const path=await a.getFilePathAsync();if(!path||!await IOUtils.exists(path))throw new Error('PDF 尚未下载或链接文件不可用；请补齐后重试。');const stat=await IOUtils.stat(path);if(stat.size>50*1024*1024)throw new Error('PDF 超过 Firework 当前 50 MiB 限制。');const bytes=await IOUtils.read(path);const check=await this.request(`/api/zotero/device/papers/${job.paperId}/attachments/check`,{library_key:job.body.library_key,item_key:job.body.item_key,attachment_key:info.key,file_hash:await this.hash(bytes)});if(check.present)continue;const w=this.win(),form=new w.FormData();form.append('file',new w.Blob([bytes],{type:'application/pdf'}),PathUtils.filename(path));for(const [k,v] of Object.entries({library_key:job.body.library_key,item_key:job.body.item_key,attachment_key:info.key,label:info.label,role:info.role}))form.append(k,v);const uploaded=await this.request(`/api/zotero/device/papers/${job.paperId}/attachments`,form,{form:true,timeout:900000});if(uploaded.fulltext_indexed===false)job.indexPending=true}
        job.status='completed';job.error='';ok++;
      }catch(e){job.status='failed';job.error=String(e.message||e);if(/timed out/i.test(job.error))job.error='请求超时，书目或 PDF 可能已保存，首次索引仍可能在处理；稍后手动重试，系统按来源和内容去重。';failed++}await this.save();
    }
    this.notice(`发送完成：${ok} 项；待处理或失败：${failed} 项。可通过“查看同步状态”查看原因，补齐附件后重试。`);
  },
  async findCollection(libraryID,parentID,name){let existing=Zotero.Collections.getByLibrary(libraryID,true).find(c=>c.parentID===parentID&&c.name===name);if(existing)return existing;const c=new Zotero.Collection();c.libraryID=libraryID;c.name=name;if(parentID)c.parentID=parentID;await c.saveTx();return c},
  normalizedDOI(value){return (value||'').trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i,'').toLowerCase()},
  async receive(){
    const pane=Zotero.getActiveZoteroPane(),libraryID=pane.getSelectedLibraryID();if(!Zotero.Libraries.get(libraryID)?.editable)throw new Error('当前文献库不可写，请选择个人库或有编辑权限的库。');
    const target=pane.getSelectedCollection();if(!Services.prompt.confirm(this.win(),'接收 Firework 论文','将接收网页中为此设备选定的论文，保存至当前文献库'+(target?'的“'+target.name+'”分类':'的 Firework 分类')+'。已有匹配书目的字段和分类保留；只有新建条目加入当前分类，原始附件保留。继续？'))return;
    let done=0;
    while(done<30){const response=await this.request('/api/zotero/device/exports/claim',{});if(!response.job)break;const job=response.job;
      const journalKey=this.pref('device')+':'+job.id;
      try{if(job.payload.item_key&&job.payload.library_key!==String(libraryID))throw new Error('此论文已关联 Zotero 文献库 '+job.payload.library_key+'，请切换到原库后重试；未创建跨库副本。');
        let entry=this.exports[journalKey];if(!entry){entry={libraryID,itemKey:job.payload.library_key===String(libraryID)&&job.payload.item_key?job.payload.item_key:Zotero.DataObjectUtilities.generateKey(),attachments:{}};this.exports[journalKey]=entry;await this.save()}
        if(entry.libraryID!==libraryID)throw new Error('此任务曾在其他文献库开始，请切回原库重试。');
        const p=job.payload;let item=await Zotero.Items.getByLibraryAndKeyAsync(libraryID,entry.itemKey);
        if(item?.deleted)throw new Error('已映射条目位于回收站，请先恢复后重试。');
        if(!item&&(p.doi||p.arxiv_id)){const all=await Zotero.Items.getAll(libraryID,true,false);const matches=all.filter(i=>i.isRegularItem()&&!i.deleted&&((p.doi&&this.normalizedDOI(i.getField('DOI'))===this.normalizedDOI(p.doi))||(p.arxiv_id&&this.arxiv(i).replace(/v\d+$/i,'')===p.arxiv_id.replace(/v\d+$/i,''))));if(matches.length>1)throw new Error('本地存在多个标识相同的条目，请先人工核对；未创建新副本。');item=matches[0];if(item){entry.itemKey=item.key;entry.created=false;await this.save()}}
        if(!item){entry.created=true;await this.save();item=new Zotero.Item('journalArticle');item.libraryID=libraryID;item.key=entry.itemKey;item.setField('title',p.title||'Untitled');if(p.doi)item.setField('DOI',p.doi);if(p.url)item.setField('url',p.url);if(p.abstract)item.setField('abstractNote',p.abstract);if(p.arxiv_id)item.setField('extra','arXiv: '+p.arxiv_id);item.setCreators((p.authors||[]).map(name=>({lastName:name,creatorType:'author',fieldMode:1})));item.setTags((p.tags||[]).map(tag=>({tag})));await item.saveTx()}
        // Existing local papers retain their collections; a receive is not a move.
        if(entry.created){let root=entry.targetCollectionID?Zotero.Collections.get(entry.targetCollectionID):null;if(!root){root=target||await this.findCollection(libraryID,false,'Firework');entry.targetCollectionID=root.id;await this.save()}const paths=p.collection_paths||[];if(!paths.length)item.addToCollection(root.id);
          for(const path of paths){let parent=root;const parts=path[0]===root.name?path.slice(1):path;for(const name of parts)parent=await this.findCollection(libraryID,parent.id,name);item.addToCollection(parent.id)}await item.saveTx()}
        for(const f of p.files){let a=entry.attachments[f.version_id]?await Zotero.Items.getByLibraryAndKeyAsync(libraryID,entry.attachments[f.version_id]):null;if(a&&(a.deleted||a.parentItemID!==item.id))a=null;const marker=this.origin()+`/api/library/papers/${p.paper_id}/document-versions/${f.version_id}/file`;
          if(!a){for(const id of item.getAttachments()){const existing=Zotero.Items.get(id);if(existing.deleted||existing.attachmentContentType!=='application/pdf')continue;if(existing.getField('url')===marker){a=existing;break}const path=await existing.getFilePathAsync();if(path&&await IOUtils.exists(path)&&await this.hash(await IOUtils.read(path))===f.file_hash){a=existing;break}}}
          if(!a){const bytes=await this.request(`/api/zotero/device/exports/${job.id}/files/${f.version_id}`,undefined,{binary:true,headers:{'X-Sync-Lease':job.lease_token}});if(await this.hash(new Uint8Array(bytes))!==f.file_hash)throw new Error('下载文件哈希不匹配，未导入。');const temp=PathUtils.join(Zotero.getTempDirectory().path,'firework-'+Zotero.Utilities.randomString(16)+'.pdf');try{await IOUtils.write(temp,new Uint8Array(bytes),{mode:'create'});await IOUtils.setPermissions(temp,0o600);a=await Zotero.Attachments.importFromFile({file:temp,parentItemID:item.id,title:f.document_title+' · '+f.label,contentType:'application/pdf'});a.setField('url',marker);await a.saveTx()}finally{await IOUtils.remove(temp,{ignoreAbsent:true})}}
          entry.attachments[f.version_id]=a.key;await this.save();
        }
        await this.request(`/api/zotero/device/exports/${job.id}/ack`,{lease_token:job.lease_token,success:true,library_key:String(libraryID),item_key:item.key,attachments:entry.attachments});done++;
      }catch(e){try{await this.request(`/api/zotero/device/exports/${job.id}/ack`,{lease_token:job.lease_token,success:false,error:String(e.message||e).slice(0,1000)})}catch{}throw e}
    }
    this.notice(`已接收 ${done} 篇论文。文件内容去重，研究模型调用为 0。`);
  },
  async hash(bytes){const h=Cc['@mozilla.org/security/hash;1'].createInstance(Ci.nsICryptoHash);h.init(h.SHA256);h.update(bytes,bytes.length);const raw=h.finish(false);return Array.from(raw,c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join('')},
  status(){const pending=this.queue.filter(j=>j.status!=='completed');const recent=this.queue.slice(-20).reverse();this.notice(`Zotero → Firework：共 ${this.queue.length} 项，待处理 ${pending.length} 项。接收队列请在网页查看。\n\n`+recent.map(j=>(j.body.title||'论文')+'：'+(j.error||({completed:'已发送',pending:'待发送',sending:'发送中',failed:'失败'}[j.status]||j.status))+(j.paperId?' · Firework #'+j.paperId:'')+(j.indexPending?' · 发送时原文可读，尚未建立全文索引':'')).join('\n'))}
};
