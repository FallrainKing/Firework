"""Normalize visible assistant text; never forward thinking or tool-input deltas."""
class LiveText:
    def __init__(self):
        self.completed=[];self.blocks={};self.started=False
    def consume(self,event):
        if event.get('parent_tool_use_id'):return None
        if event.get('type')=='stream_event':
            e=event.get('event') or {};kind=e.get('type')
            if kind=='message_start':self.blocks={};self.started=True
            elif kind=='content_block_start' and e.get('content_block',{}).get('type')=='text':self.blocks[e.get('index',0)]=e['content_block'].get('text','')
            elif kind=='content_block_delta' and e.get('delta',{}).get('type')=='text_delta':
                i=e.get('index',0);self.blocks[i]=self.blocks.get(i,'')+e['delta'].get('text','')
                return self.text()
        elif event.get('type')=='assistant':
            text='\n'.join(b.get('text','') for b in (event.get('message') or {}).get('content',[]) if b.get('type')=='text')
            if text:
                self.completed.append(text);self.blocks={};self.started=False
                return self.text()
        return None
    def text(self):return '\n\n'.join([*self.completed,*[self.blocks[k] for k in sorted(self.blocks) if self.blocks[k]]])[-256000:]
    @staticmethod
    def safe_prefix(text,secret):
        if secret:
            for n in range(min(len(secret)-1,len(text)),0,-1):
                if text.endswith(secret[:n]):text=text[:-n];break
        return text
