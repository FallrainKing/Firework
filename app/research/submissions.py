"""Local-agent results project through domain services, never fake server runs."""
import hashlib,json,uuid
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from ..core.errors import ServiceError
from ..reader.schemas import Annotation,Context
from ..reader.anchors import locate
from ..reader.service import insert_annotation_record
from .schemas import ArtifactWrite
from .service import artifact_save

class Submission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal['research-submission/v1']='research-submission/v1'
    client_job_id:str=Field(min_length=1,max_length=80,pattern='^[a-zA-Z0-9_.:-]+$')
    artifact:ArtifactWrite
    annotations:list[Annotation]=Field(default_factory=list,max_length=30)
    translation:Context|None=None
    target_language:str=Field('zh-CN',min_length=2,max_length=30)
    declared_skill:str=Field('',max_length=120)

def save(db,settings,body,token_id):
    digest=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    prior=db.execute('SELECT * FROM external_submissions WHERE token_id=? AND client_job_id=?',(token_id,body.client_job_id)).fetchone()
    if prior:
        if prior['body_hash']!=digest:raise ServiceError(409,'本机任务ID已用于不同结果')
        return json.loads(prior['receipt_json'])
    if body.artifact.source_run_id:raise ServiceError(422,'本机成果不能声明服务器Run')
    if any(a.conversation_id for a in body.annotations):raise ServiceError(422,'本机批注不绑定或伪造服务器会话')
    a=artifact_save(db,settings,body.artifact,origin='external',source_key='external:'+token_id+':'+body.client_job_id)
    ids=[]
    for annotation in body.annotations:
        if annotation.paper_id not in a['paper_ids']:raise ServiceError(422,'批注必须属于成果论文')
        anchor=locate(db,settings,annotation)
        if annotation.kind=='highlight' and anchor['status']!='located':raise ServiceError(422,'批注引句无法唯一定位，请仅提交页级笔记或明确选区')
        copy=annotation.model_copy(update={'rects':anchor['rects'] if annotation.kind=='highlight' else annotation.rects})
        ident=insert_annotation_record(db,copy)
        db.execute("UPDATE reader_annotations SET origin='ai',document_version_id=?,source_artifact_id=? WHERE id=?",(anchor['document_version_id'],a['id'],ident));ids.append(ident)
    translation_id=None
    if body.translation:
        if body.translation.paper_id not in a['paper_ids']:raise ServiceError(422,'译文必须属于成果论文')
        if not body.translation.quote.strip():raise ServiceError(422,'译文需要原文引句')
        anchor=locate(db,settings,body.translation)
        if anchor['status']!='located':raise ServiceError(422,'译文原文不能唯一定位')
        translation_id=uuid.uuid4().hex
        db.execute('INSERT INTO reader_external_translations(id,paper_id,artifact_id,page,file_version,quote,rects_json,language,answer,status) VALUES (?,?,?,?,?,?,?,?,?,?)',(translation_id,body.translation.paper_id,a['id'],body.translation.page,body.translation.file_version,body.translation.quote,json.dumps(anchor['rects']),body.target_language,body.artifact.markdown,'succeeded' if body.artifact.status=='complete' else 'partial' if body.artifact.status=='partial' else 'failed'))
    receipt={'client_job_id':body.client_job_id,'artifact_id':a['id'],'revision':a['revision'],'annotation_ids':ids,'translation_id':translation_id,'url':'/#/research?artifact='+a['id'],'origin':'external','declared_skill':body.declared_skill,'producer_verified':False,'model_called':False,'status':'saved','knowledge_published':False}
    db.execute('INSERT INTO external_submissions(token_id,client_job_id,body_hash,receipt_json) VALUES (?,?,?,?)',(token_id,body.client_job_id,digest,json.dumps(receipt)))
    return receipt
