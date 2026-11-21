import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi,beforeEach} from 'vitest'
import View from './RunnerBudgetView.vue'
import Control from '@/components/reader/RunBudgetControl.vue'
import {runnerBudgets} from '@/api/runnerBudgets'
const values={max_turns:24,max_output_tokens:8192,max_calls:24,timeout_s:1800,cost_mode:'disabled' as const,max_budget_usd:null}
const list={budgets:[{id:'standard',revision:1,name:'标准研究',builtin:true,values}],default_budget_id:null,settings_revision:1}
beforeEach(()=>{vi.restoreAllMocks();vi.spyOn(runnerBudgets,'list').mockResolvedValue(list)})
it('does not change defaults or invoke inference when opened; saves explicitly',async()=>{
 const save=vi.spyOn(runnerBudgets,'setDefault').mockResolvedValue({...list,default_budget_id:'standard',settings_revision:2})
 const w=mount(View,{global:{stubs:{RouterLink:true}}});await flushPromises()
 expect(save).not.toHaveBeenCalled()
 await w.find('select').setValue('standard')
 await w.findAll('button').find(b=>b.text()==='保存默认选择')!.trigger('click');await flushPromises()
 expect(save).toHaveBeenCalledWith('standard',1);expect(w.text()).toContain('仅影响之后创建的任务');w.unmount()
})
it('copies builtin presets and keeps cost guard disabled',async()=>{
 const save=vi.spyOn(runnerBudgets,'save').mockResolvedValue({...list.budgets[0],id:'new',builtin:false})
 const w=mount(View,{global:{stubs:{RouterLink:true}}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='复制')!.trigger('click');await w.find('form').trigger('submit');await flushPromises()
 expect(save).toHaveBeenCalledWith('标准研究（副本）',values,undefined);w.unmount()
})
it('loads per-send budgets only on demand and emits a revisioned reference',async()=>{
 const preview=vi.spyOn(runnerBudgets,'preview').mockResolvedValue({effective:{max_turns:24,max_calls:24,timeout_s:1800,max_budget_usd:null},tools:[],warning:'仅校验'})
 const w=mount(Control,{props:{modelValue:null}})
 expect(runnerBudgets.list).not.toHaveBeenCalled()
 await w.find('button').trigger('click');await flushPromises();await w.find('select').setValue('standard');await flushPromises()
 expect(w.emitted('update:modelValue')?.[0]).toEqual([{id:'standard',revision:1}]);expect(preview).toHaveBeenCalledWith('chat',{id:'standard',revision:1});w.unmount()
})
