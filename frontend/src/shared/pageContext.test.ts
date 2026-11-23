import {it,expect,vi,beforeEach} from 'vitest'
vi.mock('@/api/client',()=>({api:vi.fn(async(path:string)=>path==='/api/workbench/contexts'?{id:'ctx'}:{})}))
import {api} from '@/api/client'
import {setPageContext,enrichPageContext,publish,pageContext,startContext,stopContext} from './pageContext'
beforeEach(()=>{vi.mocked(api).mockClear();startContext()})
it('keeps source identity while the reader route changes page, excluding draft text',async()=>{
 setPageContext('reader',{paper_id:7});enrichPageContext({paper_id:7,file_hash:'a'.repeat(64),session_id:2,page:4,panel:'notes'});await publish()
 setPageContext('reader',{paper_id:7},{page:5,panel:'translations'});await publish()
 const last=vi.mocked(api).mock.calls.at(-1)![1]!.body as any
 expect(last.resource).toMatchObject({paper_id:7,file_hash:'a'.repeat(64),session_id:2});expect(last.page).toBe(5);expect(last).not.toHaveProperty('draft');expect(last.shared).toBe(false)
 setPageContext('frontier',{topic_id:8});await publish();const next=vi.mocked(api).mock.calls.at(-1)![1]!.body as any;expect(next.resource).toEqual({topic_id:8});stopContext()
})
it('creates a fresh, unshared context after logout and does not reuse the old resource',async()=>{
 setPageContext('reader',{paper_id:9});await publish();pageContext.shared=true;await publish();stopContext();await Promise.resolve();startContext();await publish()
 const bodies=vi.mocked(api).mock.calls.filter(c=>c[1]?.method==='PUT').map(c=>c[1]!.body as any)
 expect(bodies.at(-1)).toMatchObject({view:'home',resource:{},shared:false,revision:1})
 expect(vi.mocked(api).mock.calls.some(c=>c[0]==='/api/workbench/contexts'&&c[1]?.method==='POST')).toBe(true)
 stopContext()
})
