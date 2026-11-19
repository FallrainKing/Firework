import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import FrontierView from './FrontierView.vue'
import {frontierApi} from '@/api/frontier'
import {papersApi} from '@/api/papers'
const config={goal:'robot',domains:[],keywords:['robot'],authors:[],teams:[],exclude:[],sources:['crossref'],collection_ids:[],interval_hours:24,lookback_days:30,max_results:5,daily_run_limit:4}
const topic={id:1,title:'机器人前沿',revision:1,config,conversation_id:1,pending_count:1,schedule:{id:1,enabled:false,next_at:''}}
beforeEach(()=>{localStorage.clear();vi.useFakeTimers();vi.spyOn(frontierApi,'topics').mockResolvedValue({topics:[topic]});vi.spyOn(papersApi,'collections').mockResolvedValue({collections:[]});vi.spyOn(frontierApi,'items').mockResolvedValue({items:[]});vi.spyOn(frontierApi,'reports').mockResolvedValue({reports:[],next_cursor:null});vi.spyOn(frontierApi,'runs').mockResolvedValue({runs:[]})})
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks()})
describe('frontier workbench',()=>{
 it('loads management state without triggering paid work',async()=>{const spy=vi.spyOn(frontierApi,'trigger');const w=mount(FrontierView);await flushPromises();expect(w.text()).toContain('机器人前沿');expect(w.text()).toContain('暂无报告');expect(spy).not.toHaveBeenCalled();w.unmount()})
 it('creates a paused topic without executing it',async()=>{const create=vi.spyOn(frontierApi,'create').mockResolvedValue(topic);const trigger=vi.spyOn(frontierApi,'trigger');const w=mount(FrontierView);await flushPromises();await w.find('.frontier-sidebar .primary').trigger('click');await w.find('.frontier-dialog input').setValue('新主题');await w.find('.frontier-dialog textarea').setValue('robot');await w.find('form').trigger('submit');await flushPromises();expect(create).toHaveBeenCalledWith(expect.objectContaining({title:'新主题'}));expect(trigger).not.toHaveBeenCalled();w.unmount()})
 it('stacks reports and folds unchanged evidence',async()=>{const r={id:'run1',topic_id:1,topic_title:'机器人前沿',status:'partial',version:1,is_read:false,created_at:'2026-11-19 01:00:00',finished_at:'2026-11-19 01:10:00',report_md:'本期简报',counts:{new:1,known:1},items:[{id:'e1',entity_id:1,change_type:'known',metadata:{title:'已有论文'},decision:'pending',revision:1,in_library:true,paper_id:7,project_id:null}],coverage:[],usage:{},cost:null,conversation_id:1,error:null};vi.mocked(frontierApi.reports).mockResolvedValue({reports:[r],next_cursor:null});const w=mount(FrontierView);await flushPromises();expect(w.findAll('.timeline-node')).toHaveLength(1);expect(w.text()).toContain('本期简报');expect(w.find('details summary').text()).toContain('来源覆盖');expect(w.text()).toContain('已知无变化条目');expect(w.findAll('button').some(b=>b.text()==='批准入库')).toBe(false);w.unmount()})
})
